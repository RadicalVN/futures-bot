"""
sma_macd_cross_v5.py — Chiến lược V5: V4 + bộ lọc hướng MA200

Cải tiến so với V4:
  Thêm điều kiện vào lệnh dựa trên hướng của MA200 (màu slope):

  LONG: chỉ vào khi MA200 đi ngang hoặc dốc lên
    → ma_color in {"blue", "green", "yellow"}

  SHORT: chỉ vào khi MA200 đi ngang hoặc dốc xuống
    → ma_color in {"red", "orange", "yellow"}

  Màu MA200:
    blue   = dốc lên và tăng tốc
    green  = dốc lên nhưng giảm tốc
    yellow = đi ngang (slope = 0)
    orange = dốc xuống nhưng giảm tốc
    red    = dốc xuống và tăng tốc

Entry/Exit giữ nguyên như V4 (SL/TP theo % notional).
"""
import pandas as pd
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df
from src.strategies.sma_macd_cross import (
    _slope_color, _find_signal_phase_start,
    SIG_BULLISH, SIG_BEARISH,
)

# MA200 hướng cho phép vào lệnh
MA_LONG_OK  = {"blue", "green", "yellow"}   # dốc lên hoặc đi ngang
MA_SHORT_OK = {"red", "orange", "yellow"}   # dốc xuống hoặc đi ngang


class SmaMacdCrossV5Strategy(BaseStrategy):
    """
    V5 = V4 + bộ lọc hướng MA200.
    ...
    """

    STRATEGY_NAME = "sma_macd_cross_v5"
    requires_one_shot_check = True

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        signal_len = int(parameters.get("macd_signal_length", 500))
        bb_length  = int(parameters.get("bb_length",          200))
        return max(signal_len, bb_length) + 50

    async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
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
        self.leverage_v4     = int(float(self.get_param("leverage_v4", 10)))
        self.notional_usdt   = float(self.get_param("notional_usdt", 2000.0))
        self.stop_loss_pct   = float(self.get_param("stop_loss_pct", 3.0))
        self.take_profit_pct = float(self.get_param("take_profit_pct", 3.0))

    def _sl_tp_prices(self, entry_price: float, side: str) -> tuple[float, float]:
        sl_pct = self.stop_loss_pct / 100
        tp_pct = self.take_profit_pct / 100
        if side == "long":
            return entry_price * (1 - sl_pct), entry_price * (1 + tp_pct)
        else:
            return entry_price * (1 + sl_pct), entry_price * (1 - tp_pct)

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
        pos_side        = None
        pos_entry_price = 0.0
        for pos in current_positions:
            if pos.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                meta = pos.get("metadata", {}) or {}
                pos_entry_price = float(meta.get("entry_price", 0) or pos.get("entry_price", 0) or 0)
                break

        final_signal = "none"
        margin = self.notional_usdt / self.leverage_v4
        reason = (
            f"Wait | MA={ma_color} | Sig={sig_color} | MACD={macd_color} | "
            f"Close={'above' if close_curr > ma_curr else 'below'} MA"
        )
        exit_price = close_curr

        # ── EXIT (giống V4: chỉ SL/TP) ───────────────────────────────────────
        if pos_side == "long" and pos_entry_price > 0:
            sl_price, tp_price = self._sl_tp_prices(pos_entry_price, "long")
            sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
            tp_usdt = self.notional_usdt * self.take_profit_pct / 100
            if low_curr <= sl_price:
                final_signal = "close_long"
                reason = f"SL LONG: low={low_curr:.4f}<=SL={sl_price:.4f} (-{self.stop_loss_pct}%=${sl_usdt:.2f})"
                exit_price = min(sl_price, close_curr)
            elif high_curr >= tp_price:
                final_signal = "close_long"
                reason = f"TP LONG: high={high_curr:.4f}>=TP={tp_price:.4f} (+{self.take_profit_pct}%=${tp_usdt:.2f})"
                exit_price = max(tp_price, close_curr)

        elif pos_side == "short" and pos_entry_price > 0:
            sl_price, tp_price = self._sl_tp_prices(pos_entry_price, "short")
            sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
            tp_usdt = self.notional_usdt * self.take_profit_pct / 100
            if high_curr >= sl_price:
                final_signal = "close_short"
                reason = f"SL SHORT: high={high_curr:.4f}>=SL={sl_price:.4f} (-{self.stop_loss_pct}%=${sl_usdt:.2f})"
                exit_price = max(sl_price, close_curr)
            elif low_curr <= tp_price:
                final_signal = "close_short"
                reason = f"TP SHORT: low={low_curr:.4f}<=TP={tp_price:.4f} (+{self.take_profit_pct}%=${tp_usdt:.2f})"
                exit_price = min(tp_price, close_curr)

        # ── ENTRY (V4 + bộ lọc hướng MA200) ──────────────────────────────────
        elif pos_side is None:
            c1 = sig_color in SIG_BULLISH
            c2 = macd_curr >= sig_curr
            c3 = (close_prev <= ma_prev) and (close_curr > ma_curr)
            # V5: MA200 phải đi ngang hoặc dốc lên
            c4_long = ma_color in MA_LONG_OK

            if c1 and c2 and c3 and c4_long:
                ep = (high_curr + ma_curr) / 2
                dev = abs(ep - ma_curr)
                sl_p, tp_p = self._sl_tp_prices(ep, "long")
                sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
                tp_usdt = self.notional_usdt * self.take_profit_pct / 100
                return StrategySignal(
                    signal="long", symbol=symbol, price=ep,
                    reason=(
                        f"Long V5: Sig={sig_color} | MA={ma_color}(ok) | entry~{ep:.4f} | "
                        f"SL={sl_p:.4f}(-${sl_usdt:.2f}) TP={tp_p:.4f}(+${tp_usdt:.2f})"
                    ),
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_curr, 6),
                        "entry_deviation": round(dev, 6),
                        "entry_price": round(ep, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                        "leverage_v4": self.leverage_v4,
                        "notional_usdt": self.notional_usdt,
                        "stop_loss_pct": self.stop_loss_pct,
                        "take_profit_pct": self.take_profit_pct,
                    }
                )

            c1s = sig_color in SIG_BEARISH
            c2s = macd_curr <= sig_curr
            c3s = (close_prev >= ma_prev) and (close_curr < ma_curr)
            # V5: MA200 phải đi ngang hoặc dốc xuống
            c4_short = ma_color in MA_SHORT_OK

            if c1s and c2s and c3s and c4_short:
                ep = (low_curr + ma_curr) / 2
                dev = abs(ep - ma_curr)
                sl_p, tp_p = self._sl_tp_prices(ep, "short")
                sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
                tp_usdt = self.notional_usdt * self.take_profit_pct / 100
                return StrategySignal(
                    signal="short", symbol=symbol, price=ep,
                    reason=(
                        f"Short V5: Sig={sig_color} | MA={ma_color}(ok) | entry~{ep:.4f} | "
                        f"SL={sl_p:.4f}(-${sl_usdt:.2f}) TP={tp_p:.4f}(+${tp_usdt:.2f})"
                    ),
                    metadata={
                        "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                        "ma": round(ma_curr, 6), "macd": round(macd_curr, 8),
                        "macd_signal": round(sig_curr, 8), "close": round(close_curr, 6),
                        "ma_cross_price": round(ma_curr, 6),
                        "entry_deviation": round(dev, 6),
                        "entry_price": round(ep, 6),
                        "sig_phase_start_ts": sig_phase_start_ts,
                        "trend": int(df["custom_sma_trend"].iloc[-1]),
                        "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                        "momentum": ma_color,
                        "slope_pct": round(float(df["custom_sma_slope_pct"].iloc[-1]), 4),
                        "leverage_v4": self.leverage_v4,
                        "notional_usdt": self.notional_usdt,
                        "stop_loss_pct": self.stop_loss_pct,
                        "take_profit_pct": self.take_profit_pct,
                    }
                )

            # Wait detail
            if not c1 and not c1s:
                reason = f"Wait | Sig={sig_color} (need blue/green LONG, red/orange SHORT)"
            elif c1 and not c4_long:
                reason = f"Wait | Sig ok | MA={ma_color} không phù hợp LONG (cần blue/green/yellow)"
            elif c1s and not c4_short:
                reason = f"Wait | Sig ok | MA={ma_color} không phù hợp SHORT (cần red/orange/yellow)"
            elif c1 and c2 and not c3:
                reason = f"Wait | Sig+MA ok | Giá chưa cắt lên MA (close={close_curr:.2f} MA={ma_curr:.2f})"
            elif c1s and c2s and not c3s:
                reason = f"Wait | Sig+MA ok | Giá chưa cắt xuống MA (close={close_curr:.2f} MA={ma_curr:.2f})"

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
