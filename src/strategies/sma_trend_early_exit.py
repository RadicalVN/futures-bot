"""
sma_trend_early_exit.py — Chiến lược 1: Đánh Thuận Xu Hướng Sớm (Early Exit)

Ý tưởng:
- Vào lệnh khi Trend đảo chiều VÀ Gia tốc (Momentum) đang mạnh (blue/purple)
- Thoát lệnh SỚM khi Gia tốc bắt đầu suy yếu (orange/green/yellow) thay vì chờ Trend đổi màu
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df


# Trạng thái Gia tốc theo sức mạnh (ENTRY chỉ khi mạnh, EXIT sớm khi yếu)
MOMENTUM_STRONG = {"blue", "purple"}       # Đang tăng tốc / Đảo chiều vừa xảy ra
MOMENTUM_WEAKENING = {"orange", "yellow", "green"}  # Đang hãm, chuẩn bị đổi chiều


class SmaTrendEarlyExitStrategy(BaseStrategy):
    """
    Chiến lược 1: Thuận Xu Hướng + Thoát Sớm (Trend-Following with Early Exit)
    ...
    """

    STRATEGY_NAME = "sma_trend_early_exit"

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        len_c     = int(parameters.get("len_c",      200))
        bb_length = int(parameters.get("bb_length",   50))
        return max(len_c, bb_length) + 10

    async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
        """Trả về trend, momentum, slope_pct cho exit condition check."""
        try:
            df = add_custom_sma_to_df(
                df, fast_len=self.fast_len, slow_len=self.slow_len,
                len_c=self.len_c, factor=self.factor, bb_length=self.bb_length,
            )
            slope_pct = float(df["custom_sma_slope_pct"].iloc[-1])
            return {
                "trend":      int(df["custom_sma_trend"].iloc[-1]),
                "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                "momentum":   str(df["custom_sma_momentum"].iloc[-1]),
                "slope_pct":  slope_pct,
                "is_sideway": abs(slope_pct) < self.min_slope_pct,
            }
        except Exception:
            return {}

    def __init__(self, config: dict):
        super().__init__(config)
        self.fast_len = self.get_param("fast_len", 1)
        self.slow_len = self.get_param("slow_len", 5)
        self.len_c = self.get_param("len_c", 200)
        self.factor = self.get_param("factor", 0.05)
        self.bb_length = self.get_param("bb_length", 50)
        self.min_slope_pct = self.get_param("min_slope_pct", 0.0)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if len(df) < max(self.slow_len, self.len_c, self.bb_length) + 10:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Không đủ dữ liệu")

        df = add_custom_sma_to_df(
            df, fast_len=self.fast_len, slow_len=self.slow_len,
            len_c=self.len_c, factor=self.factor, bb_length=self.bb_length
        )

        current_trend = df["custom_sma_trend"].iloc[-1]
        prev_trend = df["custom_sma_trend"].iloc[-2]
        current_momentum = df["custom_sma_momentum"].iloc[-1]

        # Tính slope_pct và momentum_pct
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
        reason = f"Chờ | Trend={current_trend:.0f} | Momentum={current_momentum} | Slope={slope_pct:.4f}% | MomPct={momentum_pct:.4f}%"

        pos_side = None
        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")

        # === LOGIC THOÁT SỚM (ưu tiên kiểm tra trước) ===
        if pos_side == "long":
            if current_momentum in MOMENTUM_WEAKENING:
                final_signal = "close_long"
                reason = f"Đóng LONG sớm: Gia tốc suy yếu ({current_momentum}) | MomPct={momentum_pct:.4f}%"
            elif current_trend == -1:
                final_signal = "close_long"
                reason = f"Đóng LONG: Trend đảo Giảm"

        elif pos_side == "short":
            if current_momentum in MOMENTUM_WEAKENING:
                final_signal = "close_short"
                reason = f"Đóng SHORT sớm: Gia tốc suy yếu ({current_momentum}) | MomPct={momentum_pct:.4f}%"
            elif current_trend == 1:
                final_signal = "close_short"
                reason = f"Đóng SHORT: Trend đảo Tăng"

        # === LOGIC VÀO LỆNH ===
        elif pos_side is None:
            if current_trend == 1 and prev_trend == -1:
                if current_momentum in MOMENTUM_STRONG and abs(slope_pct) >= self.min_slope_pct:
                    final_signal = "long"
                    reason = f"Mở LONG: Trend Tăng + Gia tốc mạnh ({current_momentum}) | Slope={slope_pct:.4f}%"
                else:
                    reason = f"Bỏ qua LONG: Gia tốc chưa mạnh ({current_momentum}) | Slope={slope_pct:.4f}%"
            elif current_trend == -1 and prev_trend == 1:
                if current_momentum in MOMENTUM_STRONG and abs(slope_pct) >= self.min_slope_pct:
                    final_signal = "short"
                    reason = f"Mở SHORT: Trend Giảm + Gia tốc mạnh ({current_momentum}) | Slope={slope_pct:.4f}%"
                else:
                    reason = f"Bỏ qua SHORT: Gia tốc chưa mạnh ({current_momentum}) | Slope={slope_pct:.4f}%"

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason,
            metadata={"slope_pct": round(slope_pct, 4), "momentum_pct": round(momentum_pct, 4),
                      "momentum": current_momentum,
                      "trend": int(current_trend), "prev_trend": int(prev_trend)}
        )
