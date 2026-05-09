"""
sma_macd_cross_v2.py — Chiến lược V2: SMA + MACD Cross với bộ lọc trend

Cải tiến so với V1:
  1. Bộ lọc trend (custom_sma_trend):
     - Chỉ LONG khi custom_sma_trend = 1 (xu hướng tăng)
     - Chỉ SHORT khi custom_sma_trend = -1 (xu hướng giảm)
     - Loại bỏ lệnh ngược chiều xu hướng lớn

  2. bb_length tăng từ 50 → 150 (mặc định):
     - MA mượt hơn, ít bị cắt qua lại trong sideway
     - Tín hiệu ít hơn nhưng chất lượng cao hơn

Logic entry/exit giữ nguyên như V1.
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df
from src.strategies.sma_macd_cross import (
    _slope_color, _find_signal_phase_start,
    SIG_BULLISH, SIG_BEARISH, MA_BULLISH, MA_BEARISH,
)


class SmaMacdCrossV2Strategy(BaseStrategy):
    """
    Chiến lược SMA + MACD Cross V2 — thêm bộ lọc trend + MA dài hơn.
    ...
    """

    STRATEGY_NAME = "sma_macd_cross_v2"
    requires_one_shot_check = True

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        signal_len = int(parameters.get("macd_signal_length", 500))
        bb_length  = int(parameters.get("bb_length",          150))
        return max(signal_len, bb_length) + 50

    async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
        """Tính Custom SMA + Custom MACD colors cho exit condition check."""
        try:
            df = add_custom_sma_to_df(
                df, fast_len=self.fast_len, slow_len=self.slow_len,
                len_c=self.len_c, factor=self.factor, bb_length=self.bb_length,
            )
            df = add_custom_macd_to_df(
                df, fast=self.macd_fast, slow=self.macd_slow,
                signal_length=self.macd_signal_length,
                src=self.macd_src, sig_type=self.macd_sig_type,
            )
            ma_arr  = df["custom_sma_basis"].to_numpy()
            sig_arr = df["custom_macd_signal"].to_numpy()
            mac_arr = df["custom_macd"].to_numpy()
            i = len(df) - 1
            return {
                "ma_color":    _slope_color(ma_arr[i],  ma_arr[i-1],  ma_arr[i-2]),
                "sig_color":   _slope_color(sig_arr[i], sig_arr[i-1], sig_arr[i-2]),
                "macd_color":  _slope_color(mac_arr[i], mac_arr[i-1], mac_arr[i-2]),
                "ma":          float(ma_arr[i]),
                "macd":        float(mac_arr[i]),
                "macd_signal": float(sig_arr[i]),
                "close":       float(df["close"].iloc[-1]),
                "high":        float(df["high"].iloc[-1]),
                "low":         float(df["low"].iloc[-1]),
                "trend":       int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend":  int(df["custom_sma_trend"].iloc[-2]),
                "momentum":    str(df["custom_sma_momentum"].iloc[-1]),
                "slope_pct":   float(df["custom_sma_slope_pct"].iloc[-1]),
            }
        except Exception:
            return {}

    def __init__(self, config: dict):
        super().__init__(config)
        # SMA params
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 150)   # V2: 150 thay vì 50
        # MACD params
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")
        # V2 specific
        self.use_trend_filter = self.get_param("use_trend_filter", True)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])

        n_required = max(self.slow_len, self.len_c, self.bb_length, self.macd_signal_length) + 10
        if len(df) < n_required:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Không đủ dữ liệu")

        # ── Tính indicators ───────────────────────────────────────────────────
        df = add_custom_sma_to_df(
            df,
            fast_len=self.fast_len, slow_len=self.slow_len,
            len_c=self.len_c, factor=self.factor, bb_length=self.bb_length,
        )
        df = add_custom_macd_to_df(
            df,
            fast=self.macd_fast, slow=self.macd_slow,
            signal_length=self.macd_signal_length,
            src=self.macd_src, sig_type=self.macd_sig_type,
        )

        # ── Lấy giá trị hiện tại ─────────────────────────────────────────────
        close_curr  = float(df["close"].iloc[-1])
        close_prev  = float(df["close"].iloc[-2])
        high_curr   = float(df["high"].iloc[-1])
        low_curr    = float(df["low"].iloc[-1])

        ma_curr     = float(df["custom_sma_basis"].iloc[-1])
        ma_prev     = float(df["custom_sma_basis"].iloc[-2])
        ma_older    = float(df["custom_sma_basis"].iloc[-3])

        macd_curr   = float(df["custom_macd"].iloc[-1])
        macd_prev   = float(df["custom_macd"].iloc[-2])
        macd_older  = float(df["custom_macd"].iloc[-3])

        sig_curr    = float(df["custom_macd_signal"].iloc[-1])
        sig_prev    = float(df["custom_macd_signal"].iloc[-2])
        sig_older   = float(df["custom_macd_signal"].iloc[-3])

        # ── Trend từ custom_sma (bộ lọc V2) ──────────────────────────────────
        trend_curr = int(df["custom_sma_trend"].iloc[-1])   # 1 = tăng, -1 = giảm, 0 = chưa rõ

        # ── Tính màu slope ────────────────────────────────────────────────────
        ma_color    = _slope_color(ma_curr,   ma_prev,   ma_older)
        sig_color   = _slope_color(sig_curr,  sig_prev,  sig_older)
        macd_color  = _slope_color(macd_curr, macd_prev, macd_older)

        # ── Phase start cho one-shot ──────────────────────────────────────────
        sig_phase_start_ts = _find_signal_phase_start(df, sig_color)

        # ── Vị thế hiện tại ───────────────────────────────────────────────────
        pos_side = None
        pos_entry_deviation = 0.0
        pos_ma_cross_price  = 0.0

        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                meta = pos.get("metadata", {}) or {}
                pos_entry_deviation = float(meta.get("entry_deviation", 0) or 0)
                pos_ma_cross_price  = float(meta.get("ma_cross_price", pos.get("entry_price", 0)) or 0)
                break

        final_signal = "none"
        trend_label  = "↑" if trend_curr == 1 else ("↓" if trend_curr == -1 else "→")
        reason = (
            f"Chờ | Trend={trend_label} | MA={ma_color} | Sig={sig_color} | "
            f"MACD={macd_color} | Close={'trên' if close_curr > ma_curr else 'dưới'} MA"
        )
        exit_price = close_curr

        # ══════════════════════════════════════════════════════════════════════
        # EXIT LOGIC (giữ nguyên như V1)
        # ══════════════════════════════════════════════════════════════════════
        if pos_side == "long":
            exit_reason = None
            if sig_color in SIG_BEARISH:
                exit_reason = f"Đóng LONG TH2: Signal {sig_color}"
                exit_price = close_curr
            elif close_curr < ma_curr:
                threshold = pos_ma_cross_price + pos_entry_deviation
                if close_curr < threshold:
                    exit_price = (low_curr + ma_curr) / 2
                    exit_reason = f"Đóng LONG TH1: close<MA và <ngưỡng | Giá≈{exit_price:.4f}"
            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None
            if sig_color in SIG_BULLISH:
                exit_reason = f"Đóng SHORT TH2: Signal {sig_color}"
                exit_price = close_curr
            elif close_curr > ma_curr:
                threshold = pos_ma_cross_price + pos_entry_deviation
                if close_curr > threshold:
                    exit_price = (high_curr + ma_curr) / 2
                    exit_reason = f"Đóng SHORT TH1: close>MA và >ngưỡng | Giá≈{exit_price:.4f}"
            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ══════════════════════════════════════════════════════════════════════
        # ENTRY LOGIC — thêm bộ lọc trend (V2)
        # ══════════════════════════════════════════════════════════════════════
        elif pos_side is None:

            # ── LONG ──────────────────────────────────────────────────────────
            cond1_long = sig_color in SIG_BULLISH
            cond2_long = macd_curr >= sig_curr
            cond3_long = (close_prev <= ma_prev) and (close_curr > ma_curr)
            # V2: Điều kiện 4 — trend phải là tăng (=1)
            cond4_long = (not self.use_trend_filter) or (trend_curr == 1)

            if cond1_long and cond2_long and cond3_long and cond4_long:
                ma_cross_price  = ma_curr
                entry_price     = (high_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)
                final_signal = "long"
                reason = (
                    f"Mở LONG V2: Trend={trend_label} | Sig={sig_color} | "
                    f"MACD≥Signal | Giá cắt lên MA ({close_curr:.4f}>{ma_curr:.4f}) | "
                    f"Giá vào≈{entry_price:.4f} | Dev={entry_deviation:.4f}"
                )
                return StrategySignal(
                    signal=final_signal, symbol=symbol, price=entry_price, reason=reason,
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": trend_curr,
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # ── SHORT ─────────────────────────────────────────────────────────
            cond1_short = sig_color in SIG_BEARISH
            cond2_short = macd_curr <= sig_curr
            cond3_short = (close_prev >= ma_prev) and (close_curr < ma_curr)
            # V2: Điều kiện 4 — trend phải là giảm (=-1)
            cond4_short = (not self.use_trend_filter) or (trend_curr == -1)

            if cond1_short and cond2_short and cond3_short and cond4_short:
                ma_cross_price  = ma_curr
                entry_price     = (low_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)
                final_signal = "short"
                reason = (
                    f"Mở SHORT V2: Trend={trend_label} | Sig={sig_color} | "
                    f"MACD≤Signal | Giá cắt xuống MA ({close_curr:.4f}<{ma_curr:.4f}) | "
                    f"Giá vào≈{entry_price:.4f} | Dev={entry_deviation:.4f}"
                )
                return StrategySignal(
                    signal=final_signal, symbol=symbol, price=entry_price, reason=reason,
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": trend_curr,
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # Log wait detail
            if not cond1_long and not cond1_short:
                wait_detail = f"Sig={sig_color} (cần blue/green LONG, red/orange SHORT)"
            elif cond1_long and not cond4_long:
                wait_detail = f"Sig={sig_color}✓ | Trend={trend_label} ≠ ↑ (bộ lọc V2 chặn LONG)"
            elif cond1_short and not cond4_short:
                wait_detail = f"Sig={sig_color}✓ | Trend={trend_label} ≠ ↓ (bộ lọc V2 chặn SHORT)"
            elif cond1_long and cond2_long and not cond3_long:
                wait_detail = f"Sig✓ Trend✓ | Giá chưa cắt lên MA (close={close_curr:.2f}, MA={ma_curr:.2f})"
            elif cond1_short and cond2_short and not cond3_short:
                wait_detail = f"Sig✓ Trend✓ | Giá chưa cắt xuống MA (close={close_curr:.2f}, MA={ma_curr:.2f})"
            else:
                wait_detail = f"Trend={trend_label} | MA={ma_color} | Sig={sig_color}"

            reason = f"Chờ | {wait_detail} | Close={'trên' if close_curr > ma_curr else 'dưới'} MA"

        return StrategySignal(
            signal=final_signal, symbol=symbol,
            price=exit_price if final_signal in ("close_long", "close_short") else close_curr,
            reason=reason,
            metadata={
                "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                "sig_phase_start_ts": sig_phase_start_ts,
                "trend": trend_curr,
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color,
                "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
