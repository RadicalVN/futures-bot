"""
sma_pullback.py — Chiến lược 2: Bắt Đáy Sóng Hồi (Pullback / Buy The Dip)

Ý tưởng:
- Môi trường: Trend phải ĐANG là Xanh (Uptrend) hoặc Đỏ (Downtrend) rõ ràng
- Setup: Giá hồi lại → Momentum suy yếu về orange/yellow/green
- Trigger: Momentum bất ngờ bật mạnh trở lại (purple/blue) → Vào lệnh
  (Mua giá rẻ hơn đầu sóng, rủi ro thấp)
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df


# Trạng thái Gia tốc
MOMENTUM_STRONG_BULL = {"blue"}        # Bắt đầu tăng tốc lên mạnh
MOMENTUM_REVERSAL_BULL = {"purple"}    # Đảo chiều từ giảm sang tăng
MOMENTUM_PULLBACK = {"orange", "yellow", "green"}  # Pha hồi / điều chỉnh
MOMENTUM_STRONG_BEAR = {"red"}         # Bắt đầu tăng tốc xuống mạnh


class SmaPullbackStrategy(BaseStrategy):
    """
    Chiến lược 2: Bắt Đáy Sóng Hồi (Pullback Buy/Sell)

    Tham số cấu hình:
    - fast_len (int): Chu kỳ SMA nhanh, mặc định 1.
    - slow_len (int): Chu kỳ SMA chậm, mặc định 5.
    - len_c (int): Chu kỳ làm mượt tổng hợp, mặc định 200.
    - factor (float): Hệ số nhiễu đảo chiều Trend, mặc định 0.05.
    - bb_length (int): Chu kỳ SMA Bollinger cơ sở, mặc định 50.
    - pullback_confirm_bars (int): Số nến cần xác nhận pha hồi trước khi Trigger, mặc định 2.
    - min_slope_pct (float): Ngưỡng dốc tối thiểu khi trigger, mặc định 0.0.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_pullback"
        self.fast_len = self.get_param("fast_len", 1)
        self.slow_len = self.get_param("slow_len", 5)
        self.len_c = self.get_param("len_c", 200)
        self.factor = self.get_param("factor", 0.05)
        self.bb_length = self.get_param("bb_length", 50)
        self.pullback_confirm_bars = self.get_param("pullback_confirm_bars", 2)
        self.min_slope_pct = self.get_param("min_slope_pct", 0.0)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        n_required = max(self.slow_len, self.len_c, self.bb_length) + self.pullback_confirm_bars + 5
        if len(df) < n_required:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Không đủ dữ liệu")

        df = add_custom_sma_to_df(
            df, fast_len=self.fast_len, slow_len=self.slow_len,
            len_c=self.len_c, factor=self.factor, bb_length=self.bb_length
        )

        current_trend = df["custom_sma_trend"].iloc[-1]
        current_momentum = df["custom_sma_momentum"].iloc[-1]

        # Kiểm tra pha pullback: các nến gần nhất có momentum yếu
        lookback = self.pullback_confirm_bars
        recent_momentums = df["custom_sma_momentum"].iloc[-(lookback + 1):-1].tolist()
        was_in_pullback = all(m in MOMENTUM_PULLBACK for m in recent_momentums)

        # Slope và Momentum pct
        basis = df["custom_sma_basis"]
        slope_pct = 0.0
        momentum_pct = 0.0
        if len(basis) >= 3 and not pd.isna(basis.iloc[-2]) and basis.iloc[-2] != 0:
            slope_pct = (basis.iloc[-1] - basis.iloc[-2]) / basis.iloc[-2] * 100
            projected = 2 * basis.iloc[-2] - basis.iloc[-3]
            if projected != 0:
                momentum_pct = (basis.iloc[-1] - projected) / projected * 100

        current_price = df["close"].iloc[-1]
        final_signal = "none"
        reason = (f"Chờ | Trend={current_trend:.0f} | Momentum={current_momentum} | "
                  f"WasPullback={was_in_pullback} | Slope={slope_pct:.4f}%")

        pos_side = None
        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")

        # === LOGIC THOÁT LỆNH ===
        if pos_side == "long":
            if current_trend == -1 or current_momentum in MOMENTUM_STRONG_BEAR:
                final_signal = "close_long"
                reason = f"Đóng LONG: Trend đảo hoặc Gia tốc giảm mạnh ({current_momentum})"
        elif pos_side == "short":
            if current_trend == 1 or current_momentum in MOMENTUM_STRONG_BULL:
                final_signal = "close_short"
                reason = f"Đóng SHORT: Trend đảo hoặc Gia tốc tăng mạnh ({current_momentum})"

        # === LOGIC VÀO LỆNH (Bắt sóng hồi) ===
        elif pos_side is None:
            # LONG PULLBACK: Trend đang Xanh, vừa qua pha hồi, momentum bật lại
            if (current_trend == 1
                    and was_in_pullback
                    and current_momentum in (MOMENTUM_STRONG_BULL | MOMENTUM_REVERSAL_BULL)
                    and slope_pct >= self.min_slope_pct):
                final_signal = "long"
                reason = (f"Mở LONG pullback: Trend Xanh + Hồi {lookback} nến + Bật ({current_momentum}) | "
                          f"Slope={slope_pct:.4f}%")

            # SHORT PULLBACK: Trend đang Đỏ, vừa qua pha hồi ngược, momentum bật xuống lại
            elif (current_trend == -1
                    and was_in_pullback
                    and current_momentum in MOMENTUM_STRONG_BEAR
                    and slope_pct <= -self.min_slope_pct):
                final_signal = "short"
                reason = (f"Mở SHORT pullback: Trend Đỏ + Hồi {lookback} nến + Rớt ({current_momentum}) | "
                          f"Slope={slope_pct:.4f}%")

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason,
            metadata={"slope_pct": round(slope_pct, 4), "momentum_pct": round(momentum_pct, 4),
                      "momentum": current_momentum, "was_in_pullback": was_in_pullback}
        )
