"""
sma_anti_sideway.py — Chiến lược 3: Bộ Lọc Sideway Chống Nhiễu (Anti-Whipsaw)

Ý tưởng:
- Dùng |% Dốc| (slope_pct) làm bộ lọc: nếu SMA đang đi ngang (slope yếu), bỏ qua mọi tín hiệu
- Chỉ ra lệnh khi cả Slope VÀ Momentum đều đủ mạnh (thị trường đang chạy thật sự)
- Thoát lệnh khi slope yếu đi (thị trường dần về trạng thái tích luỹ)
"""
import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal
from src.data.indicators import add_custom_sma_to_df


class SmaAntiSidewayStrategy(BaseStrategy):
    """
    Chiến lược 3: Chống Nhiễu Sideway (Anti-Whipsaw Filter)

    Tham số cấu hình:
    - fast_len (int): Chu kỳ SMA nhanh, mặc định 1.
    - slow_len (int): Chu kỳ SMA chậm, mặc định 5.
    - len_c (int): Chu kỳ làm mượt tổng hợp, mặc định 200.
    - factor (float): Hệ số nhiễu đảo chiều Trend, mặc định 0.05.
    - bb_length (int): Chu kỳ SMA Bollinger cơ sở, mặc định 50.
    - sideway_slope_threshold (float): Ngưỡng |% Dốc| tối thiểu để coi là thị trường ĐANG CHẠY (không sideway).
        Nếu |slope_pct| < threshold → Bot ngủ đông. Mặc định 0.01 (%).
    - exit_slope_threshold (float): Ngưỡng |% Dốc| để đóng lệnh sớm khi thị trường quay về tích luỹ.
        Mặc định bằng sideway_slope_threshold.
    - min_momentum_pct (float): Ngưỡng |% Gia tốc| tối thiểu để confirm thêm. Mặc định 0.0.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "sma_anti_sideway"
        self.fast_len = self.get_param("fast_len", 1)
        self.slow_len = self.get_param("slow_len", 5)
        self.len_c = self.get_param("len_c", 200)
        self.factor = self.get_param("factor", 0.05)
        self.bb_length = self.get_param("bb_length", 50)
        self.sideway_slope_threshold = self.get_param("sideway_slope_threshold", 0.01)
        self.exit_slope_threshold = self.get_param("exit_slope_threshold", self.sideway_slope_threshold)
        self.min_momentum_pct = self.get_param("min_momentum_pct", 0.0)

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

        abs_slope = abs(slope_pct)
        abs_mom = abs(momentum_pct)
        is_sideway = abs_slope < self.sideway_slope_threshold
        is_exiting_trend = abs_slope < self.exit_slope_threshold

        current_price = df["close"].iloc[-1]
        final_signal = "none"

        if is_sideway:
            reason = (f"😴 Ngủ đông (Sideway): |Slope|={abs_slope:.4f}% < {self.sideway_slope_threshold}% | "
                      f"Momentum={current_momentum}")
            return StrategySignal(signal="none", symbol=symbol, price=current_price, reason=reason,
                                  metadata={"slope_pct": round(slope_pct, 4), "is_sideway": True})

        reason = (f"Chờ | Trend={current_trend:.0f} | Momentum={current_momentum} | "
                  f"Slope={slope_pct:.4f}% | MomPct={momentum_pct:.4f}%")

        pos_side = None
        for pos in current_positions:
            pos_sym = pos.get("symbol", "").replace("/", "")
            if pos_sym == symbol.replace("/", ""):
                pos_side = pos.get("side", "")

        # === LOGIC THOÁT LỆNH ===
        if pos_side == "long":
            if is_exiting_trend and current_trend == 1:
                # Slope đang thu hẹp → chuẩn bị đi ngang, chốt lời
                final_signal = "close_long"
                reason = f"Đóng LONG: Slope thu hẹp ({abs_slope:.4f}%), thị trường đang về tích luỹ"
            elif current_trend == -1:
                final_signal = "close_long"
                reason = f"Đóng LONG: Trend đảo Giảm | Slope={slope_pct:.4f}%"

        elif pos_side == "short":
            if is_exiting_trend and current_trend == -1:
                final_signal = "close_short"
                reason = f"Đóng SHORT: Slope thu hẹp ({abs_slope:.4f}%), thị trường đang về tích luỹ"
            elif current_trend == 1:
                final_signal = "close_short"
                reason = f"Đóng SHORT: Trend đảo Tăng | Slope={slope_pct:.4f}%"

        # === LOGIC VÀO LỆNH ===
        elif pos_side is None:
            meets_momentum = abs_mom >= self.min_momentum_pct

            if current_trend == 1 and prev_trend == -1 and meets_momentum:
                final_signal = "long"
                reason = (f"Mở LONG: Trend Tăng | Slope={slope_pct:.4f}% (mạnh) | "
                          f"MomPct={momentum_pct:.4f}%")
            elif current_trend == -1 and prev_trend == 1 and meets_momentum:
                final_signal = "short"
                reason = (f"Mở SHORT: Trend Giảm | Slope={slope_pct:.4f}% (mạnh) | "
                          f"MomPct={momentum_pct:.4f}%")

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason,
            metadata={"slope_pct": round(slope_pct, 4), "momentum_pct": round(momentum_pct, 4),
                      "momentum": current_momentum, "is_sideway": False}
        )
