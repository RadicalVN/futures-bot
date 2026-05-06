"""
sma_macd_cross_v6.py — Chiến lược: SMA + MACD Cross + ADX Filter (TuanTV1008)

Base: sma_macd_cross_v1 (sma_macd_cross.py)
Thay đổi so với V1: ADX filter cho cả entry VÀ exit, với ngưỡng tách biệt.

─── ENTRY LONG ───────────────────────────────────────────────────────────────
  Điều kiện 1: MACD-Signal đang màu xanh lá HOẶC xanh dương
  Điều kiện 2: MACD đang hoặc đã cắt lên trên Signal (macd >= signal)
  Điều kiện 3: Nến đóng cửa trên MA (giá cắt qua MA từ dưới lên)
  Điều kiện 4: ADX > adx_entry_threshold (env: ADX_ENTRY_THRESHOLD, mặc định 25)
  → Giá vào = (high_curr + ma_curr) / 2
  → Lưu độ lệch = |giá vào - ma_curr|

─── EXIT LONG ────────────────────────────────────────────────────────────────
  Bắt buộc: ADX > adx_exit_threshold (env: ADX_EXIT_THRESHOLD, mặc định 25)
            Nếu không thỏa → giữ lệnh, chờ tín hiệu rõ hơn
  TH1 (có chọn lọc): close < MA VÀ close < (ma_cross_price + entry_deviation)
      → Đóng với giá = (low_curr + ma_curr) / 2
  TH2 (ngay lập tức): MACD-Signal chuyển đỏ hoặc cam
                      VÀ close < ma_curr (giá đóng phiên dưới TVT-MA)

─── ENTRY SHORT ──────────────────────────────────────────────────────────────
  Điều kiện 1: MACD-Signal đang màu cam HOẶC đỏ
  Điều kiện 2: MACD đang hoặc đã cắt xuống dưới Signal (macd <= signal)
  Điều kiện 3: Nến đóng cửa dưới MA (giá cắt qua MA từ trên xuống)
  Điều kiện 4: ADX > adx_entry_threshold (env: ADX_ENTRY_THRESHOLD, mặc định 25)
  → Giá vào = (low_curr + ma_curr) / 2
  → Lưu độ lệch = |giá vào - ma_curr|

─── EXIT SHORT ───────────────────────────────────────────────────────────────
  Bắt buộc: ADX > adx_exit_threshold (env: ADX_EXIT_THRESHOLD, mặc định 25)
            Nếu không thỏa → giữ lệnh, chờ tín hiệu rõ hơn
  TH1 (có chọn lọc): close > MA VÀ close > (ma_cross_price + deviation)
      → Đóng với giá = (high_curr + ma_curr) / 2
  TH2 (ngay lập tức): MACD-Signal chuyển xanh lá hoặc xanh dương
                      VÀ close > ma_curr (giá đóng phiên trên TVT-MA)
"""
import os
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df, add_adx_to_df

# Đọc ngưỡng ADX từ env — tách biệt entry và exit
_ADX_PERIOD_DEFAULT  = int(float(os.environ.get("ADX_PERIOD", 14)))
_ADX_ENTRY_DEFAULT   = float(os.environ.get("ADX_ENTRY_THRESHOLD", 25.0))
_ADX_EXIT_DEFAULT    = float(os.environ.get("ADX_EXIT_THRESHOLD",  25.0))


# ── Nhóm màu ──────────────────────────────────────────────────────────────────
SIG_BULLISH = {"blue", "green"}    # MACD-Signal tích cực → điều kiện entry LONG
SIG_BEARISH = {"red", "orange"}    # MACD-Signal tiêu cực → điều kiện entry SHORT


def _slope_color(curr: float, prev: float, older: float) -> str:
    """
    Tính màu slope từ 3 điểm liên tiếp — giống rule chart.js slopeColor:
      curr > prev + tăng tốc  → blue
      curr > prev + giảm tốc  → green
      curr < prev + tăng tốc  → red
      curr < prev + giảm tốc  → orange
      curr == prev            → yellow
    """
    if curr == prev:
        return "yellow"
    slope_curr = curr - prev
    slope_prev = prev - older
    if curr > prev:
        return "blue" if slope_curr >= slope_prev else "green"
    else:
        return "red" if slope_curr <= slope_prev else "orange"


def _find_signal_phase_start(df: pd.DataFrame, current_sig_color: str) -> int:
    """
    Tìm timestamp (ms) của nến đầu tiên trong phase Signal hiện tại.
    Phase = chuỗi nến liên tục mà Signal cùng nhóm màu (bullish hoặc bearish).
    """
    if current_sig_color in SIG_BULLISH:
        phase_group = SIG_BULLISH
    elif current_sig_color in SIG_BEARISH:
        phase_group = SIG_BEARISH
    else:
        return int(df["timestamp"].iloc[-1])

    sig_arr = df["custom_macd_signal"].to_numpy()
    n = len(df)

    phase_start_idx = n - 1
    for i in range(n - 1, 1, -1):
        color_i = _slope_color(sig_arr[i], sig_arr[i - 1], sig_arr[i - 2])
        if color_i not in phase_group:
            phase_start_idx = i + 1
            break
        phase_start_idx = i

    return int(df["timestamp"].iloc[phase_start_idx])


class SmaMacdCrossV6Strategy(BaseStrategy):
    """
    Chiến lược SMA + MACD Cross + ADX Filter — V6.

    Tham số mới so với V1:
    - adx_period (int)           : Chu kỳ ADX, mặc định 14
    - adx_entry_threshold (float): Ngưỡng ADX để VÀO lệnh (env ADX_ENTRY_THRESHOLD, mặc định 25)
    - adx_exit_threshold (float) : Ngưỡng ADX để ĐÓNG lệnh (env ADX_EXIT_THRESHOLD, mặc định 25)

    Tham số kế thừa từ V1:
    - fast_len, slow_len, len_c, factor, bb_length
    - macd_fast, macd_slow, macd_signal_length, macd_src, macd_sig_type
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross_v6"
        # SMA params
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 200)
        # MACD params
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")
        # ADX params — tách biệt entry / exit
        self.adx_period          = self.get_param("adx_period", _ADX_PERIOD_DEFAULT)
        self.adx_entry_threshold = self.get_param("adx_entry_threshold", _ADX_ENTRY_DEFAULT)
        self.adx_exit_threshold  = self.get_param("adx_exit_threshold",  _ADX_EXIT_DEFAULT)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])

        n_required = max(self.slow_len, self.len_c, self.bb_length, self.macd_signal_length, self.adx_period * 2) + 10
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
        df = add_adx_to_df(df, period=self.adx_period)

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

        adx_curr    = float(df["adx"].iloc[-1])

        # ── Tính màu slope ────────────────────────────────────────────────────
        ma_color    = _slope_color(ma_curr,   ma_prev,   ma_older)
        sig_color   = _slope_color(sig_curr,  sig_prev,  sig_older)
        macd_color  = _slope_color(macd_curr, macd_prev, macd_older)

        # ── Tìm điểm bắt đầu phase Signal hiện tại ───────────────────────────
        sig_phase_start_ts = _find_signal_phase_start(df, sig_color)

        # ── Xác định vị thế hiện tại của bot này ─────────────────────────────
        pos_side = None
        pos_entry_price = 0.0
        pos_entry_deviation = 0.0
        pos_ma_cross_price = 0.0

        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                pos_entry_price = float(pos.get("entry_price", 0) or 0)
                meta = pos.get("metadata", {}) or {}
                pos_entry_deviation = float(meta.get("entry_deviation", 0) or 0)
                pos_ma_cross_price  = float(meta.get("ma_cross_price", pos_entry_price) or pos_entry_price)
                break

        final_signal = "none"
        reason = (
            f"Chờ | MA={ma_color} | Sig={sig_color} | MACD={macd_color} | "
            f"ADX={adx_curr:.2f} | "
            f"Close={'trên' if close_curr > ma_curr else 'dưới'} MA"
        )
        exit_price = close_curr

        # ══════════════════════════════════════════════════════════════════════
        # EXIT LOGIC — kiểm tra trước entry
        # ══════════════════════════════════════════════════════════════════════
        if pos_side == "long":
            exit_reason = None

            # Điều kiện bắt buộc cho exit: ADX > adx_exit_threshold
            adx_exit_ok = adx_curr > self.adx_exit_threshold

            if not adx_exit_ok:
                reason = (
                    f"Giữ LONG: ADX={adx_curr:.2f} ≤ {self.adx_exit_threshold} "
                    f"(xu hướng yếu, chưa đóng) | Sig={sig_color}"
                )
            else:
                # TH2 (ưu tiên cao): MACD-Signal chuyển bearish
                #   VÀ close < ma_curr (giá đóng phiên dưới TVT-MA)
                if sig_color in SIG_BEARISH and close_curr < ma_curr:
                    exit_reason = (
                        f"Đóng LONG TH2: Signal={sig_color} (bearish)"
                        f" | close={close_curr:.4f} < MA={ma_curr:.4f}✓"
                        f" | ADX={adx_curr:.2f}>{self.adx_exit_threshold}✓"
                    )
                    exit_price = close_curr

                # TH1 (có chọn lọc): close < MA VÀ close < (ma_cross_price + deviation)
                elif close_curr < ma_curr:
                    threshold = pos_ma_cross_price + pos_entry_deviation
                    if close_curr < threshold:
                        exit_price = (low_curr + ma_curr) / 2
                        exit_reason = (
                            f"Đóng LONG TH1: close={close_curr:.4f} < MA={ma_curr:.4f}"
                            f" và < ngưỡng={threshold:.4f}"
                            f" (cross={pos_ma_cross_price:.4f} + dev={pos_entry_deviation:.4f})"
                            f" | ADX={adx_curr:.2f}>{self.adx_exit_threshold}✓"
                            f" | Giá đóng ≈ {exit_price:.4f}"
                        )

            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None

            # Điều kiện bắt buộc cho exit: ADX > adx_exit_threshold
            adx_exit_ok = adx_curr > self.adx_exit_threshold

            if not adx_exit_ok:
                reason = (
                    f"Giữ SHORT: ADX={adx_curr:.2f} ≤ {self.adx_exit_threshold} "
                    f"(xu hướng yếu, chưa đóng) | Sig={sig_color}"
                )
            else:
                # TH2 (ưu tiên cao): MACD-Signal chuyển bullish
                #   VÀ close > ma_curr (giá đóng phiên trên TVT-MA)
                if sig_color in SIG_BULLISH and close_curr > ma_curr:
                    exit_reason = (
                        f"Đóng SHORT TH2: Signal={sig_color} (bullish)"
                        f" | close={close_curr:.4f} > MA={ma_curr:.4f}✓"
                        f" | ADX={adx_curr:.2f}>{self.adx_exit_threshold}✓"
                    )
                    exit_price = close_curr

                # TH1 (có chọn lọc): close > MA VÀ close > (ma_cross_price + deviation)
                elif close_curr > ma_curr:
                    threshold = pos_ma_cross_price + pos_entry_deviation
                    if close_curr > threshold:
                        exit_price = (high_curr + ma_curr) / 2
                        exit_reason = (
                            f"Đóng SHORT TH1: close={close_curr:.4f} > MA={ma_curr:.4f}"
                            f" và > ngưỡng={threshold:.4f}"
                            f" (cross={pos_ma_cross_price:.4f} + dev={pos_entry_deviation:.4f})"
                            f" | ADX={adx_curr:.2f}>{self.adx_exit_threshold}✓"
                            f" | Giá đóng ≈ {exit_price:.4f}"
                        )

            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ══════════════════════════════════════════════════════════════════════
        # ENTRY LOGIC
        # ══════════════════════════════════════════════════════════════════════
        elif pos_side is None:

            # Điều kiện 4: ADX > adx_entry_threshold
            cond4 = adx_curr > self.adx_entry_threshold

            # ── LONG ──────────────────────────────────────────────────────────
            cond1_long = sig_color in SIG_BULLISH
            cond2_long = macd_curr >= sig_curr
            cond3_long = (close_prev <= ma_prev) and (close_curr > ma_curr)

            if cond1_long and cond2_long and cond3_long and cond4:
                ma_cross_price  = ma_curr
                entry_price     = (high_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)

                final_signal = "long"
                reason = (
                    f"Mở LONG: Sig={sig_color} (bullish) | "
                    f"MACD={macd_curr:.6f} ≥ Signal={sig_curr:.6f} | "
                    f"Giá cắt lên MA ({close_curr:.4f}>{ma_curr:.4f}) | "
                    f"ADX={adx_curr:.2f}>{self.adx_entry_threshold} | "
                    f"Giá vào≈{entry_price:.4f} | Dev={entry_deviation:.4f} | "
                    f"Phase ts={sig_phase_start_ts}"
                )
                return StrategySignal(
                    signal=final_signal,
                    symbol=symbol,
                    price=entry_price,
                    reason=reason,
                    metadata={
                        "ma_color": ma_color,
                        "sig_color": sig_color,
                        "macd_color": macd_color,
                        "ma": round(ma_curr, 6),
                        "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8),
                        "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "adx": round(adx_curr, 4),
                        "adx_entry_threshold": self.adx_entry_threshold,
                        "adx_exit_threshold":  self.adx_exit_threshold,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # ── SHORT ─────────────────────────────────────────────────────────
            cond1_short = sig_color in SIG_BEARISH
            cond2_short = macd_curr <= sig_curr
            cond3_short = (close_prev >= ma_prev) and (close_curr < ma_curr)

            if cond1_short and cond2_short and cond3_short and cond4:
                ma_cross_price  = ma_curr
                entry_price     = (low_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)

                final_signal = "short"
                reason = (
                    f"Mở SHORT: Sig={sig_color} (bearish) | "
                    f"MACD={macd_curr:.6f} ≤ Signal={sig_curr:.6f} | "
                    f"Giá cắt xuống MA ({close_curr:.4f}<{ma_curr:.4f}) | "
                    f"ADX={adx_curr:.2f}>{self.adx_entry_threshold} | "
                    f"Giá vào≈{entry_price:.4f} | Dev={entry_deviation:.4f} | "
                    f"Phase ts={sig_phase_start_ts}"
                )
                return StrategySignal(
                    signal=final_signal,
                    symbol=symbol,
                    price=entry_price,
                    reason=reason,
                    metadata={
                        "ma_color": ma_color,
                        "sig_color": sig_color,
                        "macd_color": macd_color,
                        "ma": round(ma_curr, 6),
                        "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8),
                        "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "adx": round(adx_curr, 4),
                        "adx_entry_threshold": self.adx_entry_threshold,
                        "adx_exit_threshold":  self.adx_exit_threshold,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # ── Log chi tiết khi chờ ──────────────────────────────────────────
            if not cond1_long and not cond1_short:
                wait_detail = f"Sig={sig_color} (cần blue/green cho LONG, red/orange cho SHORT)"
            elif cond1_long and not cond2_long:
                wait_detail = f"Sig={sig_color}✓ | MACD({macd_curr:.6f}) < Signal({sig_curr:.6f}) — chờ golden cross"
            elif cond1_long and cond2_long and not cond3_long:
                wait_detail = f"Sig={sig_color}✓ | MACD≥Signal✓ | Giá chưa cắt lên MA (close={close_curr:.4f}, MA={ma_curr:.4f})"
            elif cond1_long and cond2_long and cond3_long and not cond4:
                wait_detail = f"Sig={sig_color}✓ | MACD≥Signal✓ | Giá cắt lên MA✓ | ADX={adx_curr:.2f} ≤ {self.adx_entry_threshold} (xu hướng yếu)"
            elif cond1_short and not cond2_short:
                wait_detail = f"Sig={sig_color}✓ | MACD({macd_curr:.6f}) > Signal({sig_curr:.6f}) — chờ death cross"
            elif cond1_short and cond2_short and not cond3_short:
                wait_detail = f"Sig={sig_color}✓ | MACD≤Signal✓ | Giá chưa cắt xuống MA (close={close_curr:.4f}, MA={ma_curr:.4f})"
            elif cond1_short and cond2_short and cond3_short and not cond4:
                wait_detail = f"Sig={sig_color}✓ | MACD≤Signal✓ | Giá cắt xuống MA✓ | ADX={adx_curr:.2f} ≤ {self.adx_entry_threshold} (xu hướng yếu)"
            else:
                wait_detail = f"MA={ma_color} | Sig={sig_color} | MACD={macd_color} | ADX={adx_curr:.2f}"

            reason = f"Chờ | {wait_detail} | Close={'trên' if close_curr > ma_curr else 'dưới'} MA"

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=exit_price if final_signal in ("close_long", "close_short") else close_curr,
            reason=reason,
            metadata={
                "ma_color": ma_color,
                "sig_color": sig_color,
                "macd_color": macd_color,
                "ma": round(ma_curr, 6),
                "macd": round(macd_curr, 8),
                "macd_signal": round(sig_curr, 8),
                "close": round(close_curr, 6),
                "sig_phase_start_ts": sig_phase_start_ts,
                "adx": round(adx_curr, 4),
                "adx_entry_threshold": self.adx_entry_threshold,
                "adx_exit_threshold":  self.adx_exit_threshold,
                "trend": int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color,
                "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
