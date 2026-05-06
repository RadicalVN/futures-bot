"""
sma_macd_cross_v7.py — Chiến lược: SMA + MACD Cross V7 (TuanTV1008)

Base: sma_macd_cross_v1 (sma_macd_cross.py)
Thay đổi so với V1:

  ENTRY — Điều kiện 1 thay đổi:
    LONG : MACD-Signal > 0  (thay vì màu xanh)
    SHORT: MACD-Signal < 0  (thay vì màu đỏ/cam)

  EXIT — Bỏ TH2, chỉ còn TH1 với điều kiện bổ sung Bollinger Bands:
    EXIT LONG  (TH1): close < MA
                      VÀ close < (ma_cross_price + entry_deviation)
                      VÀ close > bb_upper  (giá phá vỡ lên Dải Trên BB)
                      VÀ MACD-Signal màu đỏ hoặc cam (bearish)
                      → Giá đóng = (low_curr + ma_curr) / 2
    EXIT SHORT (TH1): close > MA
                      VÀ close > (ma_cross_price + entry_deviation)
                      VÀ close < bb_lower  (giá phá vỡ xuống Dải Dưới BB)
                      VÀ MACD-Signal màu xanh dương hoặc xanh lá (bullish)
                      → Giá đóng = (high_curr + ma_curr) / 2

─── ENTRY LONG ───────────────────────────────────────────────────────────────
  Điều kiện 1: MACD-Signal > 0
  Điều kiện 2: MACD >= Signal (macd >= signal)
  Điều kiện 3: Nến đóng cửa trên MA (giá cắt qua MA từ dưới lên)
  Điều kiện 4: TVT-MA màu xanh dương hoặc xanh lá (custom_sma_momentum in blue/green)
  → Giá vào = (high_curr + ma_curr) / 2

─── EXIT LONG ────────────────────────────────────────────────────────────────
  TH1: close < MA
       VÀ close < (ma_cross_price + entry_deviation)
       VÀ close > bb_upper
       VÀ MACD-Signal màu đỏ hoặc cam (bearish)
       → Giá đóng = (low_curr + ma_curr) / 2

─── ENTRY SHORT ──────────────────────────────────────────────────────────────
  Điều kiện 1: MACD-Signal < 0
  Điều kiện 2: MACD <= Signal (macd <= signal)
  Điều kiện 3: Nến đóng cửa dưới MA (giá cắt qua MA từ trên xuống)
  Điều kiện 4: TVT-MA màu đỏ hoặc cam (custom_sma_momentum in red/orange)
  → Giá vào = (low_curr + ma_curr) / 2

─── EXIT SHORT ───────────────────────────────────────────────────────────────
  TH1: close > MA
       VÀ close > (ma_cross_price + entry_deviation)
       VÀ close < bb_lower
       VÀ MACD-Signal màu xanh dương hoặc xanh lá (bullish)
       → Giá đóng = (high_curr + ma_curr) / 2
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df, add_bb_to_df


SIG_BULLISH = {"blue", "green"}
SIG_BEARISH = {"red", "orange"}


def _slope_color(curr: float, prev: float, older: float) -> str:
    import math as _m
    if _m.isnan(curr) or _m.isnan(prev) or _m.isnan(older):
        return "yellow"
    if curr == prev:
        return "yellow"
    slope_curr = curr - prev
    slope_prev = prev - older
    if curr > prev:
        return "blue" if slope_curr >= slope_prev else "green"
    else:
        return "red" if slope_curr <= slope_prev else "orange"


def _find_signal_phase_start(df: pd.DataFrame, current_sig_color: str) -> int:
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


class SmaMacdCrossV7Strategy(BaseStrategy):
    """
    Chiến lược SMA + MACD Cross V7.

    Tham số mới so với V1:
    - bb_period (int)  : Chu kỳ Bollinger Bands, mặc định 20
    - bb_mult (float)  : Hệ số std BB, mặc định 2.0

    Tham số kế thừa từ V1:
    - fast_len, slow_len, len_c, factor, bb_length
    - macd_fast, macd_slow, macd_signal_length, macd_src, macd_sig_type
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross_v7"
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
        # Bollinger Bands params (V7 mới)
        self.bb_period = self.get_param("bb_period", 20)
        self.bb_mult   = self.get_param("bb_mult",   2.0)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])

        n_required = max(
            self.slow_len, self.len_c, self.bb_length,
            self.macd_signal_length, self.bb_period,
        ) + 10
        if len(df) < n_required:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Khong du du lieu")

        # Tinh indicators
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
        df = add_bb_to_df(df, period=self.bb_period, mult=self.bb_mult)

        # Lay gia tri hien tai
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

        bb_upper   = float(df["bb_upper"].iloc[-1])
        bb_lower   = float(df["bb_lower"].iloc[-1])
        bb_middle  = float(df["bb_middle"].iloc[-1])

        # custom_sma_trend: +1 = uptrend (TVT-MA xanh), -1 = downtrend (TVT-MA do/cam)
        sma_trend  = int(df["custom_sma_trend"].iloc[-1])

        ma_color   = _slope_color(ma_curr,   ma_prev,   ma_older)
        sig_color  = _slope_color(sig_curr,  sig_prev,  sig_older)
        macd_color = _slope_color(macd_curr, macd_prev, macd_older)

        # TVT-MA color: lay tu custom_sma_momentum (tinh stateful, nhat quan voi bieu do)
        tvt_ma_color = str(df["custom_sma_momentum"].iloc[-1])

        sig_phase_start_ts = _find_signal_phase_start(df, sig_color)

        # Xac dinh vi the hien tai
        pos_side            = None
        pos_entry_deviation = 0.0
        pos_ma_cross_price  = 0.0

        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                pos_ep   = float(pos.get("entry_price", 0) or 0)
                meta     = pos.get("metadata", {}) or {}
                pos_entry_deviation = float(meta.get("entry_deviation", 0) or 0)
                pos_ma_cross_price  = float(meta.get("ma_cross_price", pos_ep) or pos_ep)
                break

        final_signal = "none"
        reason = (
            f"Cho | MA={ma_color} | Sig={sig_curr:.6f} | MACD={macd_color} | "
            f"BB_U={bb_upper:.4f} BB_L={bb_lower:.4f} | "
            f"Close={'tren' if close_curr > ma_curr else 'duoi'} MA"
        )
        exit_price = close_curr

        # ======================================================================
        # EXIT LOGIC — chi TH1, khong co TH2
        # ======================================================================
        if pos_side == "long":
            exit_reason = None

            # TH1: close < MA
            #      VA close < (ma_cross_price + entry_deviation)
            #      VA close > bb_upper  (pha vo len Dai Tren)
            #      VA MACD-Signal mau do hoac cam (bearish)
            if close_curr < ma_curr:
                threshold = pos_ma_cross_price + pos_entry_deviation
                if (close_curr < threshold
                        and close_curr > bb_upper
                        and sig_color in SIG_BEARISH):
                    exit_price = (low_curr + ma_curr) / 2
                    exit_reason = (
                        f"Dong LONG TH1: close={close_curr:.4f} < MA={ma_curr:.4f}"
                        f" | < nguong={threshold:.4f}"
                        f" | > BB_Upper={bb_upper:.4f} (pha vo len)✓"
                        f" | Signal={sig_color} (bearish)✓"
                        f" | Gia dong ≈ {exit_price:.4f}"
                    )

            if exit_reason:
                final_signal = "close_long"
                reason = exit_reason

        elif pos_side == "short":
            exit_reason = None

            # TH1: close > MA
            #      VA close > (ma_cross_price + entry_deviation)
            #      VA close < bb_lower  (pha vo xuong Dai Duoi)
            #      VA MACD-Signal mau xanh duong hoac xanh la (bullish)
            if close_curr > ma_curr:
                threshold = pos_ma_cross_price + pos_entry_deviation
                if (close_curr > threshold
                        and close_curr < bb_lower
                        and sig_color in SIG_BULLISH):
                    exit_price = (high_curr + ma_curr) / 2
                    exit_reason = (
                        f"Dong SHORT TH1: close={close_curr:.4f} > MA={ma_curr:.4f}"
                        f" | > nguong={threshold:.4f}"
                        f" | < BB_Lower={bb_lower:.4f} (pha vo xuong)✓"
                        f" | Signal={sig_color} (bullish)✓"
                        f" | Gia dong ≈ {exit_price:.4f}"
                    )

            if exit_reason:
                final_signal = "close_short"
                reason = exit_reason

        # ======================================================================
        # ENTRY LOGIC
        # ======================================================================
        elif pos_side is None:

            # LONG
            # Dieu kien 1 (V7): MACD-Signal > 0
            cond1_long = sig_curr > 0
            # Dieu kien 2: MACD >= Signal
            cond2_long = macd_curr >= sig_curr
            # Dieu kien 3: Gia cat len MA
            cond3_long = (close_prev <= ma_prev) and (close_curr > ma_curr)
            # Dieu kien 4: TVT-MA mau xanh duong hoac xanh la (dung custom_sma_momentum)
            cond4_long = tvt_ma_color in {"blue", "green"}

            if cond1_long and cond2_long and cond3_long and cond4_long:
                ma_cross_price  = ma_curr
                entry_price     = (high_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)

                final_signal = "long"
                reason = (
                    f"Mo LONG: Signal={sig_curr:.6f}>0✓ | "
                    f"MACD={macd_curr:.6f}>=Signal={sig_curr:.6f} | "
                    f"Gia cat len MA ({close_curr:.4f}>{ma_curr:.4f}) | "
                    f"TVT-MA={tvt_ma_color}✓ | "
                    f"Gia vao≈{entry_price:.4f} | Dev={entry_deviation:.4f} | "
                    f"Phase ts={sig_phase_start_ts}"
                )
                return StrategySignal(
                    signal=final_signal,
                    symbol=symbol,
                    price=entry_price,
                    reason=reason,
                    metadata={
                        "ma_color": ma_color,
                        "tvt_ma_color": tvt_ma_color,
                        "sig_color": sig_color,
                        "macd_color": macd_color,
                        "ma": round(ma_curr, 6),
                        "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8),
                        "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "bb_upper": round(bb_upper, 6),
                        "bb_lower": round(bb_lower, 6),
                        "bb_middle": round(bb_middle, 6),
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": tvt_ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # SHORT
            # Dieu kien 1 (V7): MACD-Signal < 0
            cond1_short = sig_curr < 0
            # Dieu kien 2: MACD <= Signal
            cond2_short = macd_curr <= sig_curr
            # Dieu kien 3: Gia cat xuong MA
            cond3_short = (close_prev >= ma_prev) and (close_curr < ma_curr)
            # Dieu kien 4: TVT-MA mau do hoac cam (dung custom_sma_momentum)
            cond4_short = tvt_ma_color in {"red", "orange"}

            if cond1_short and cond2_short and cond3_short and cond4_short:
                ma_cross_price  = ma_curr
                entry_price     = (low_curr + ma_cross_price) / 2
                entry_deviation = abs(entry_price - ma_cross_price)

                final_signal = "short"
                reason = (
                    f"Mo SHORT: Signal={sig_curr:.6f}<0✓ | "
                    f"MACD={macd_curr:.6f}<=Signal={sig_curr:.6f} | "
                    f"Gia cat xuong MA ({close_curr:.4f}<{ma_curr:.4f}) | "
                    f"TVT-MA={tvt_ma_color}✓ | "
                    f"Gia vao≈{entry_price:.4f} | Dev={entry_deviation:.4f} | "
                    f"Phase ts={sig_phase_start_ts}"
                )
                return StrategySignal(
                    signal=final_signal,
                    symbol=symbol,
                    price=entry_price,
                    reason=reason,
                    metadata={
                        "ma_color": ma_color,
                        "tvt_ma_color": tvt_ma_color,
                        "sig_color": sig_color,
                        "macd_color": macd_color,
                        "ma": round(ma_curr, 6),
                        "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8),
                        "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_cross_price, 6),
                        "entry_deviation": round(entry_deviation, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "bb_upper": round(bb_upper, 6),
                        "bb_lower": round(bb_lower, 6),
                        "bb_middle": round(bb_middle, 6),
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": tvt_ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                    }
                )

            # Log chi tiet khi cho
            if not cond1_long and not cond1_short:
                wait_detail = (
                    f"Signal={sig_curr:.6f} "
                    f"(can >0 cho LONG, <0 cho SHORT)"
                )
            elif cond1_long and not cond2_long:
                wait_detail = (
                    f"Signal={sig_curr:.6f}>0✓ | "
                    f"MACD({macd_curr:.6f}) < Signal — cho golden cross"
                )
            elif cond1_long and cond2_long and not cond3_long:
                wait_detail = (
                    f"Signal>0✓ | MACD>=Signal✓ | "
                    f"Gia chua cat len MA (close={close_curr:.4f}, MA={ma_curr:.4f})"
                )
            elif cond1_long and cond2_long and cond3_long and not cond4_long:
                wait_detail = (
                    f"Signal>0✓ | MACD>=Signal✓ | Gia cat len MA✓ | "
                    f"TVT-MA={tvt_ma_color} (can blue/green)"
                )
            elif cond1_short and not cond2_short:
                wait_detail = (
                    f"Signal={sig_curr:.6f}<0✓ | "
                    f"MACD({macd_curr:.6f}) > Signal — cho death cross"
                )
            elif cond1_short and cond2_short and not cond3_short:
                wait_detail = (
                    f"Signal<0✓ | MACD<=Signal✓ | "
                    f"Gia chua cat xuong MA (close={close_curr:.4f}, MA={ma_curr:.4f})"
                )
            elif cond1_short and cond2_short and cond3_short and not cond4_short:
                wait_detail = (
                    f"Signal<0✓ | MACD<=Signal✓ | Gia cat xuong MA✓ | "
                    f"TVT-MA={tvt_ma_color} (can red/orange)"
                )
            else:
                wait_detail = (
                    f"MA={ma_color} | Signal={sig_curr:.6f} | MACD={macd_color}"
                )

            reason = (
                f"Cho | {wait_detail} | "
                f"Close={'tren' if close_curr > ma_curr else 'duoi'} MA | "
                f"BB_U={bb_upper:.4f} BB_L={bb_lower:.4f}"
            )

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
                "bb_upper": round(bb_upper, 6),
                "bb_lower": round(bb_lower, 6),
                "bb_middle": round(bb_middle, 6),
                "trend": int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum": ma_color,
                "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
            }
        )
