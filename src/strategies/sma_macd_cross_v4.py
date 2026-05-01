"""
sma_macd_cross_v4.py — Chiến lược V4: SMA + MACD Cross, SL/TP theo % vốn lệnh

Dựa trên V1 (sma_macd_cross):
  - Entry: giữ nguyên như V1 (3 điều kiện + one-shot)
  - Exit: CHỈ dùng SL/TP theo % — bỏ TH1/TH2/TH3

Tham số riêng của V4:
  - leverage_v4 (int): đòn bẩy, mặc định 10
  - notional_usdt (float): vốn lệnh sau đòn bẩy (USDT), mặc định 2000
    → margin thực bỏ ra = notional_usdt / leverage_v4 = 200$
  - stop_loss_pct (float): % cắt lỗ tính trên notional, mặc định 3.0
    → lỗ tối đa = notional × 3% = 60$
  - take_profit_pct (float): % chốt lời tính trên notional, mặc định 3.0
    → lãi mục tiêu = notional × 3% = 60$

Cách tính SL/TP price từ % notional:
  LONG:
    sl_price = entry - (notional × sl_pct/100) / size
    tp_price = entry + (notional × tp_pct/100) / size
  SHORT:
    sl_price = entry + (notional × sl_pct/100) / size
    tp_price = entry - (notional × tp_pct/100) / size

  Trong đó: size = notional / entry_price
  → sl_price = entry × (1 - sl_pct/100)  [vì (notional × pct) / (notional/entry) = entry × pct]
  → Kết quả giống % giá, nhưng ý nghĩa là % trên notional (đúng với futures)
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
    V4 = V1 + SL/TP theo % vốn lệnh (notional).

    Tham số:
    - leverage_v4 (int): đòn bẩy, mặc định 10
    - notional_usdt (float): vốn lệnh sau đòn bẩy (USDT), mặc định 2000
    - stop_loss_pct (float): % cắt lỗ trên notional, mặc định 3.0
    - take_profit_pct (float): % chốt lời trên notional, mặc định 3.0
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_macd_cross_v4"
        # SMA params (giống V1)
        self.fast_len    = self.get_param("fast_len", 1)
        self.slow_len    = self.get_param("slow_len", 5)
        self.len_c       = self.get_param("len_c", 200)
        self.factor      = self.get_param("factor", 0.05)
        self.bb_length   = self.get_param("bb_length", 200)
        # MACD params (giống V1)
        self.macd_fast          = self.get_param("macd_fast", 12)
        self.macd_slow          = self.get_param("macd_slow", 26)
        self.macd_signal_length = self.get_param("macd_signal_length", 500)
        self.macd_src           = self.get_param("macd_src", "EMA")
        self.macd_sig_type      = self.get_param("macd_sig_type", "EMA")
        # V4: position sizing + SL/TP
        self.leverage_v4     = int(float(self.get_param("leverage_v4", 10)))
        self.notional_usdt   = float(self.get_param("notional_usdt", 2000.0))
        self.stop_loss_pct   = float(self.get_param("stop_loss_pct", 3.0))
        self.take_profit_pct = float(self.get_param("take_profit_pct", 3.0))

    def _sl_tp_prices(self, entry_price: float, side: str) -> tuple[float, float]:
        """
        Tính giá SL và TP từ % notional.

        Với futures isolated margin:
          PnL = size × (exit - entry) × direction
          size = notional / entry_price
          PnL_target = notional × pct/100

          → price_change = PnL_target / size = (notional × pct/100) / (notional/entry) = entry × pct/100
          → sl_price = entry × (1 ∓ sl_pct/100)
          → tp_price = entry × (1 ± tp_pct/100)

        Kết quả: % giá = % notional (đúng với isolated margin futures).
        """
        sl_pct = self.stop_loss_pct / 100
        tp_pct = self.take_profit_pct / 100
        if side == "long":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)
        return sl, tp

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

        # Lay thong tin vi the hien tai
        pos_side        = None
        pos_entry_price = 0.0

        for pos in current_positions:
            if pos.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                pos_side = pos.get("side", "")
                meta = pos.get("metadata", {}) or {}
                # Uu tien entry_price tu metadata (chinh xac hon exchange entry_price)
                pos_entry_price = float(meta.get("entry_price", 0) or pos.get("entry_price", 0) or 0)
                break

        final_signal = "none"
        margin = self.notional_usdt / self.leverage_v4
        reason = (
            f"Wait | MA={ma_color} | Sig={sig_color} | MACD={macd_color} | "
            f"Close={'above' if close_curr > ma_curr else 'below'} MA | "
            f"Notional=${self.notional_usdt:.0f} Lev={self.leverage_v4}x Margin=${margin:.0f}"
        )
        exit_price = close_curr

        # ══════════════════════════════════════════════════════════════════════
        # EXIT: chỉ SL/TP theo % notional
        # ══════════════════════════════════════════════════════════════════════
        if pos_side == "long" and pos_entry_price > 0:
            sl_price, tp_price = self._sl_tp_prices(pos_entry_price, "long")
            sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
            tp_usdt = self.notional_usdt * self.take_profit_pct / 100

            # Dung low/high de check intrabar (chinh xac hon close)
            if low_curr <= sl_price:
                final_signal = "close_long"
                reason = (
                    f"SL LONG: low={low_curr:.4f} <= SL={sl_price:.4f} | "
                    f"-{self.stop_loss_pct}% notional = -${sl_usdt:.2f}"
                )
                exit_price = min(sl_price, close_curr)
            elif high_curr >= tp_price:
                final_signal = "close_long"
                reason = (
                    f"TP LONG: high={high_curr:.4f} >= TP={tp_price:.4f} | "
                    f"+{self.take_profit_pct}% notional = +${tp_usdt:.2f}"
                )
                exit_price = max(tp_price, close_curr)

        elif pos_side == "short" and pos_entry_price > 0:
            sl_price, tp_price = self._sl_tp_prices(pos_entry_price, "short")
            sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
            tp_usdt = self.notional_usdt * self.take_profit_pct / 100

            # Dung high/low de check intrabar
            if high_curr >= sl_price:
                final_signal = "close_short"
                reason = (
                    f"SL SHORT: high={high_curr:.4f} >= SL={sl_price:.4f} | "
                    f"-{self.stop_loss_pct}% notional = -${sl_usdt:.2f}"
                )
                exit_price = max(sl_price, close_curr)
            elif low_curr <= tp_price:
                final_signal = "close_short"
                reason = (
                    f"TP SHORT: low={low_curr:.4f} <= TP={tp_price:.4f} | "
                    f"+{self.take_profit_pct}% notional = +${tp_usdt:.2f}"
                )
                exit_price = min(tp_price, close_curr)

        # ══════════════════════════════════════════════════════════════════════
        # ENTRY: giống V1
        # ══════════════════════════════════════════════════════════════════════
        elif pos_side is None:
            c1 = sig_color in SIG_BULLISH
            c2 = macd_curr >= sig_curr
            c3 = (close_prev <= ma_prev) and (close_curr > ma_curr)

            if c1 and c2 and c3:
                ep = (high_curr + ma_curr) / 2
                dev = abs(ep - ma_curr)
                sl_p, tp_p = self._sl_tp_prices(ep, "long")
                sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
                tp_usdt = self.notional_usdt * self.take_profit_pct / 100
                return StrategySignal(
                    signal="long", symbol=symbol, price=ep,
                    reason=(
                        f"Long V4: Sig={sig_color} | entry~{ep:.4f} | "
                        f"Notional=${self.notional_usdt:.0f} Lev={self.leverage_v4}x | "
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

            if c1s and c2s and c3s:
                ep = (low_curr + ma_curr) / 2
                dev = abs(ep - ma_curr)
                sl_p, tp_p = self._sl_tp_prices(ep, "short")
                sl_usdt = self.notional_usdt * self.stop_loss_pct / 100
                tp_usdt = self.notional_usdt * self.take_profit_pct / 100
                return StrategySignal(
                    signal="short", symbol=symbol, price=ep,
                    reason=(
                        f"Short V4: Sig={sig_color} | entry~{ep:.4f} | "
                        f"Notional=${self.notional_usdt:.0f} Lev={self.leverage_v4}x | "
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
            elif c1 and not c2:
                reason = f"Wait | Sig ok | MACD < Signal — wait golden cross"
            elif c1 and c2 and not c3:
                reason = f"Wait | Sig+MACD ok | Price not crossed MA up (close={close_curr:.2f} MA={ma_curr:.2f})"
            elif c1s and not c2s:
                reason = f"Wait | Sig ok | MACD > Signal — wait death cross"
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
