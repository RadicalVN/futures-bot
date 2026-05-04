"""
sma_macd_cross_v3.py — Chiến lược V3: SMA + MACD Cross

Cải tiến so với V2:
  1. bb_length = 200 (V2: 150)
  2. min_ma_distance_pct: giá phải cách MA ít nhất X% khi vào lệnh (mặc định 0.1%)
  3. min_hold_candles: không exit TH1 trước N nến (mặc định 3), TH2/TH3 vẫn exit ngay
"""
import pandas as pd
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df
from src.strategies.sma_macd_cross import (
    _slope_color, _find_signal_phase_start,
    SIG_BULLISH, SIG_BEARISH,
)


class SmaMacdCrossV3Strategy(BaseStrategy):

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross_v3"
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 200)
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")
        self.use_trend_filter    = self.get_param("use_trend_filter", True)
        self.min_ma_distance_pct = self.get_param("min_ma_distance_pct", 0.1)
        self.min_hold_candles    = self.get_param("min_hold_candles", 3)

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
        trend_curr = int(df["custom_sma_trend"].iloc[-1])

        ma_color   = _slope_color(ma_curr,   ma_prev,   ma_older)
        sig_color  = _slope_color(sig_curr,  sig_prev,  sig_older)
        macd_color = _slope_color(macd_curr, macd_prev, macd_older)
        sig_phase_start_ts = _find_signal_phase_start(df, sig_color)

        # Lay thong tin vi the hien tai
        pos_side            = None
        pos_entry_deviation = 0.0
        pos_ma_cross_price  = 0.0
        pos_entry_candle_ts = 0

        for pos in current_positions:
            if pos.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                meta = pos.get("metadata", {}) or {}
                pos_entry_deviation = float(meta.get("entry_deviation", 0) or 0)
                pos_ma_cross_price  = float(meta.get("ma_cross_price", pos.get("entry_price", 0)) or 0)
                pos_entry_candle_ts = int(meta.get("entry_candle_ts", 0) or 0)
                break

        # Tinh so nen da giu lenh
        candles_held = 0
        if pos_side and pos_entry_candle_ts:
            ts_arr = [int(t) for t in df["timestamp"].tolist()]
            try:
                entry_idx = next(i for i, t in enumerate(ts_arr) if t >= pos_entry_candle_ts)
                candles_held = len(ts_arr) - 1 - entry_idx
            except StopIteration:
                candles_held = 0

        trend_label  = "up" if trend_curr == 1 else ("dn" if trend_curr == -1 else "flat")
        final_signal = "none"
        reason = f"Wait | Trend={trend_label} | MA={ma_color} | Sig={sig_color} | MACD={macd_color}"
        exit_price = close_curr

        # ── EXIT ─────────────────────────────────────────────────────────────
        if pos_side == "long":
            exit_reason = None
            if sig_color in SIG_BEARISH:
                exit_reason = f"Close LONG TH2: Signal {sig_color}"
                exit_price = close_curr
            elif close_curr < ma_curr:
                if candles_held >= self.min_hold_candles:
                    threshold = pos_ma_cross_price + pos_entry_deviation
                    if close_curr < threshold:
                        exit_price = (low_curr + ma_curr) / 2
                        exit_reason = f"Close LONG TH1: hold={candles_held} | price~{exit_price:.4f}"
                else:
                    reason = f"Hold LONG: close<MA but hold={candles_held}<{self.min_hold_candles}"
            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None
            if sig_color in SIG_BULLISH:
                exit_reason = f"Close SHORT TH2: Signal {sig_color}"
                exit_price = close_curr
            elif close_curr > ma_curr:
                if candles_held >= self.min_hold_candles:
                    threshold = pos_ma_cross_price + pos_entry_deviation
                    if close_curr > threshold:
                        exit_price = (high_curr + ma_curr) / 2
                        exit_reason = f"Close SHORT TH1: hold={candles_held} | price~{exit_price:.4f}"
                else:
                    reason = f"Hold SHORT: close>MA but hold={candles_held}<{self.min_hold_candles}"
            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ── ENTRY ─────────────────────────────────────────────────────────────
        elif pos_side is None:
            ma_dist_pct = abs(close_curr - ma_curr) / ma_curr * 100 if ma_curr else 0

            # LONG
            c1 = sig_color in SIG_BULLISH
            c2 = macd_curr >= sig_curr
            c3 = (close_prev <= ma_prev) and (close_curr > ma_curr)
            c4 = (not self.use_trend_filter) or (trend_curr == 1)
            c5 = ma_dist_pct >= self.min_ma_distance_pct

            if c1 and c2 and c3 and c4 and c5:
                ma_cross = ma_curr
                ep = (high_curr + ma_cross) / 2
                dev = abs(ep - ma_cross)
                curr_ts = int(df["timestamp"].iloc[-1])
                return StrategySignal(
                    signal="long", symbol=symbol, price=ep,
                    reason=f"Long V3: Trend={trend_label} Sig={sig_color} Dist={ma_dist_pct:.3f}% entry~{ep:.2f}",
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross, 6), "entry_deviation": round(dev, 6),
                        "entry_candle_ts": curr_ts, "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": trend_curr, "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color, "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # SHORT
            c1s = sig_color in SIG_BEARISH
            c2s = macd_curr <= sig_curr
            c3s = (close_prev >= ma_prev) and (close_curr < ma_curr)
            c4s = (not self.use_trend_filter) or (trend_curr == -1)
            c5s = ma_dist_pct >= self.min_ma_distance_pct

            if c1s and c2s and c3s and c4s and c5s:
                ma_cross = ma_curr
                ep = (low_curr + ma_cross) / 2
                dev = abs(ep - ma_cross)
                curr_ts = int(df["timestamp"].iloc[-1])
                return StrategySignal(
                    signal="short", symbol=symbol, price=ep,
                    reason=f"Short V3: Trend={trend_label} Sig={sig_color} Dist={ma_dist_pct:.3f}% entry~{ep:.2f}",
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross, 6), "entry_deviation": round(dev, 6),
                        "entry_candle_ts": curr_ts, "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": trend_curr, "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color, "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # Wait detail
            if not c1 and not c1s:
                reason = f"Wait | Sig={sig_color} (need blue/green LONG, red/orange SHORT)"
            elif c1 and not c4:
                reason = f"Wait | Sig={sig_color} ok | Trend={trend_label} != up (V3 filter)"
            elif c1s and not c4s:
                reason = f"Wait | Sig={sig_color} ok | Trend={trend_label} != dn (V3 filter)"
            elif (c1 or c1s) and not c5:
                reason = f"Wait | Dist={ma_dist_pct:.3f}% < {self.min_ma_distance_pct}% (too close to MA)"
            elif c1 and c2 and not c3:
                reason = f"Wait | Sig+Trend ok | Price not crossed MA up (close={close_curr:.2f} MA={ma_curr:.2f})"
            elif c1s and c2s and not c3s:
                reason = f"Wait | Sig+Trend ok | Price not crossed MA dn (close={close_curr:.2f} MA={ma_curr:.2f})"

        return StrategySignal(
            signal=final_signal, symbol=symbol,
            price=exit_price if final_signal in ("close_long", "close_short") else close_curr,
            reason=reason,
            metadata={
                "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                "sig_phase_start_ts": sig_phase_start_ts,
                "trend": trend_curr, "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color, "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
