"""
sma_macd_cross_v4.py — Chiến lược V4: SMA + MACD Cross, chỉ dùng SL/TP theo %

Dựa trên V1 (sma_macd_cross):
  - Entry: giữ nguyên hoàn toàn như V1 (3 điều kiện + one-shot)
  - Exit: CHỈ dùng SL/TP theo % — bỏ hoàn toàn TH1/TH2/TH3

Tham số:
  - stop_loss_pct (float): % cắt lỗ từ giá vào, mặc định 3.0
  - take_profit_pct (float): % chốt lời từ giá vào, mặc định 3.0

LONG:
  - SL: close <= entry_price * (1 - stop_loss_pct/100)
  - TP: close >= entry_price * (1 + take_profit_pct/100)

SHORT:
  - SL: close >= entry_price * (1 + stop_loss_pct/100)
  - TP: close <= entry_price * (1 - take_profit_pct/100)
"""
import pandas as pd
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df
from src.strategies.sma_macd_cross import (
    _slope_color, _find_signal_phase_start,
    SIG_BULLISH, SIG_BEARISH,
)


class SmaMacdCrossV4Strategy(BaseStrategy):
    """
    V4 = V1 + SL/TP theo %.

    Tham số:
    - stop_loss_pct (float): % cắt lỗ từ giá vào, mặc định 3.0
    - take_profit_pct (float): % chốt lời từ giá vào, mặc định 3.0
    - (tất cả tham số V1 giữ nguyên)
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross_v4"
        # SMA params (giống V1)
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 50)
        # MACD params (giống V1)
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")
        # V4: SL/TP theo %
        self.stop_loss_pct   = float(self.get_param("stop_loss_pct", 3.0))
        self.take_profit_pct = float(self.get_param("take_profit_pct", 3.0))

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])

        n_required = max(self.slow_len, self.len_c, self.bb_length, self.macd_signal_length) + 10
        if len(df) < n_required:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Khong du du lieu")

        df = add_custom_sma_to_df(df, fast_len=self.fast_len, slow_len=self.slow_len,
                                   len_c=self.len_c, factor=self.factor, bb_length=self.bb_length)
        df = add_custom_macd_to_df(df, fast=self.macd_fast, slow=self.macd_slow,
                                    signal_length=self.macd_signal_length,
                                    src=self.macd_src, sig_type=self.macd_sig_type)

        close_curr = float(df["close"].iloc[-1])
        close_prev = float(df["close"].iloc[-2])
        high_curr  = float(df["high"].iloc[-1])
        low_curr   = float(df["low"].iloc[-1])
        ma_curr    = float(df["custom_sma_basis"].iloc[-1])
        ma_prev    = float(df["custom_sma_basis"].iloc[-2])
        ma_older   = float(df["custom_sma_basis"].iloc[-3])
        macd_curr  = float(df["custom_macd"].iloc[-1])
        macd_prev  = float(df["custom_macd"].iloc[-2])
        macd_older = float(df["custom_macd"].iloc[-3])
        sig_curr   = float(df["custom_macd_signal"].iloc[-1])
        sig_prev   = float(df["custom_macd_signal"].iloc[-2])
        sig_older  = float(df["custom_macd_signal"].iloc[-3])

        ma_color   = _slope_color(ma_curr,   ma_prev,   ma_older)
        sig_color  = _slope_color(sig_curr,  sig_prev,  sig_older)
        macd_color = _slope_color(macd_curr, macd_prev, macd_older)
        sig_phase_start_ts = _find_signal_phase_start(df, sig_color)

        # Lay thong tin vi the
        pos_side            = None
        pos_entry_price     = 0.0
        pos_entry_deviation = 0.0
        pos_ma_cross_price  = 0.0

        for pos in current_positions:
            if pos.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                pos_entry_price = float(pos.get("entry_price", 0) or 0)
                meta = pos.get("metadata", {}) or {}
                pos_entry_deviation = float(meta.get("entry_deviation", 0) or 0)
                pos_ma_cross_price  = float(meta.get("ma_cross_price", pos_entry_price) or pos_entry_price)
                # Uu tien lay entry_price tu metadata neu co
                if meta.get("entry_price"):
                    pos_entry_price = float(meta["entry_price"])
                break

        final_signal = "none"
        reason = (
            f"Wait | MA={ma_color} | Sig={sig_color} | MACD={macd_color} | "
            f"Close={'above' if close_curr > ma_curr else 'below'} MA"
        )
        exit_price = close_curr

        # ══════════════════════════════════════════════════════════════════════
        # EXIT LOGIC
        # ══════════════════════════════════════════════════════════════════════
        if pos_side == "long":
            exit_reason = None

            # Chi SL/TP theo % — bo TH1/TH2/TH3
            if pos_entry_price > 0:
                sl_price = pos_entry_price * (1 - self.stop_loss_pct / 100)
                tp_price = pos_entry_price * (1 + self.take_profit_pct / 100)

                if close_curr <= sl_price:
                    exit_reason = (
                        f"SL LONG: close={close_curr:.4f} <= SL={sl_price:.4f} "
                        f"({self.stop_loss_pct}% tu entry={pos_entry_price:.4f})"
                    )
                    exit_price = close_curr
                elif close_curr >= tp_price:
                    exit_reason = (
                        f"TP LONG: close={close_curr:.4f} >= TP={tp_price:.4f} "
                        f"({self.take_profit_pct}% tu entry={pos_entry_price:.4f})"
                    )
                    exit_price = close_curr

            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None

            # Chi SL/TP theo % — bo TH1/TH2/TH3
            if pos_entry_price > 0:
                sl_price = pos_entry_price * (1 + self.stop_loss_pct / 100)
                tp_price = pos_entry_price * (1 - self.take_profit_pct / 100)

                if close_curr >= sl_price:
                    exit_reason = (
                        f"SL SHORT: close={close_curr:.4f} >= SL={sl_price:.4f} "
                        f"({self.stop_loss_pct}% tu entry={pos_entry_price:.4f})"
                    )
                    exit_price = close_curr
                elif close_curr <= tp_price:
                    exit_reason = (
                        f"TP SHORT: close={close_curr:.4f} <= TP={tp_price:.4f} "
                        f"({self.take_profit_pct}% tu entry={pos_entry_price:.4f})"
                    )
                    exit_price = close_curr

            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ══════════════════════════════════════════════════════════════════════
        # ENTRY LOGIC (giong V1)
        # ══════════════════════════════════════════════════════════════════════
        elif pos_side is None:

            # LONG
            c1 = sig_color in SIG_BULLISH
            c2 = macd_curr >= sig_curr
            c3 = (close_prev <= ma_prev) and (close_curr > ma_curr)

            if c1 and c2 and c3:
                ma_cross = ma_curr
                ep = (high_curr + ma_cross) / 2
                dev = abs(ep - ma_cross)
                return StrategySignal(
                    signal="long", symbol=symbol, price=ep,
                    reason=(
                        f"Long V4: Sig={sig_color} | MACD>={sig_curr:.6f} | "
                        f"Price crossed MA up | entry~{ep:.4f} | "
                        f"SL={ep*(1-self.stop_loss_pct/100):.4f} TP={ep*(1+self.take_profit_pct/100):.4f}"
                    ),
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross, 6),
                        "entry_deviation": round(dev, 6),
                        "entry_price": round(ep, 6),  # luu de tinh SL/TP
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                        "stop_loss_pct": self.stop_loss_pct,
                        "take_profit_pct": self.take_profit_pct,
                    }
                )

            # SHORT
            c1s = sig_color in SIG_BEARISH
            c2s = macd_curr <= sig_curr
            c3s = (close_prev >= ma_prev) and (close_curr < ma_curr)

            if c1s and c2s and c3s:
                ma_cross = ma_curr
                ep = (low_curr + ma_cross) / 2
                dev = abs(ep - ma_cross)
                return StrategySignal(
                    signal="short", symbol=symbol, price=ep,
                    reason=(
                        f"Short V4: Sig={sig_color} | MACD<={sig_curr:.6f} | "
                        f"Price crossed MA dn | entry~{ep:.4f} | "
                        f"SL={ep*(1+self.stop_loss_pct/100):.4f} TP={ep*(1-self.take_profit_pct/100):.4f}"
                    ),
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross, 6),
                        "entry_deviation": round(dev, 6),
                        "entry_price": round(ep, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                        "stop_loss_pct": self.stop_loss_pct,
                        "take_profit_pct": self.take_profit_pct,
                    }
                )

            # Wait detail
            if not c1 and not c1s:
                reason = f"Wait | Sig={sig_color} (need blue/green LONG, red/orange SHORT)"
            elif c1 and not c2:
                reason = f"Wait | Sig={sig_color} ok | MACD({macd_curr:.6f}) < Signal — wait golden cross"
            elif c1 and c2 and not c3:
                reason = f"Wait | Sig+MACD ok | Price not crossed MA up (close={close_curr:.2f} MA={ma_curr:.2f})"
            elif c1s and not c2s:
                reason = f"Wait | Sig={sig_color} ok | MACD({macd_curr:.6f}) > Signal — wait death cross"
            elif c1s and c2s and not c3s:
                reason = f"Wait | Sig+MACD ok | Price not crossed MA dn (close={close_curr:.2f} MA={ma_curr:.2f})"

        return StrategySignal(
            signal=final_signal, symbol=symbol,
            price=exit_price if final_signal in ("close_long", "close_short") else close_curr,
            reason=reason,
            metadata={
                "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                "sig_phase_start_ts": sig_phase_start_ts,
                "trend": int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color,
                "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
