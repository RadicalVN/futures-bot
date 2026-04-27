import pandas as pd
import numpy as np
from src.strategies.base_strategy import BaseStrategy, StrategySignal

class CustomSMAStrategy(BaseStrategy):
    """
    Chiến thuật giao dịch dựa trên chỉ báo Custom SMA (ittuantruong).
    
    Phương pháp hoạt động:
    1. Tính toán trung bình động (SMA) nhanh và chậm, sau đó kết hợp và làm mượt thêm.
    2. Xác định đường trung tâm (center_line) và tạo dải băng trên (band_up), dải băng dưới (band_dn).
    3. Xác định xu hướng (trend_direction) dựa trên cấu trúc dải băng và hệ số nhiễu (factor).
    4. Cung cấp tín hiệu LONG khi xu hướng chuyển Tăng (1) và SHORT khi xu hướng chuyển Giảm (-1).
    """

    def __init__(self, config: dict):
        """
        Khởi tạo các tham số cho chiến thuật Custom SMA:
        - fast_length: Chu kỳ của đường SMA nhanh.
        - slow_length: Chu kỳ của đường SMA chậm.
        - signal_length: Chu kỳ dùng để làm mượt đường trung bình tổng hợp.
        - factor: Hệ số xác định sự đảo chiều xu hướng, giúp lọc các tín hiệu nhiễu.
        - bb_length: Chu kỳ của dải Bollinger Bands cải tiến (mặc định 50).
        - bb_mult: Hệ số nhân độ lệch chuẩn của Bollinger Bands (mặc định 2.0).
        """
        super().__init__(config)
        self.name = "custom_sma"
        self.fast_length = self.get_param("fast_length", 1)
        self.slow_length = self.get_param("slow_length", 5)
        self.signal_length = self.get_param("len_c", 20)
        self.trend_factor = self.get_param("factor", 0.05)
        self.bb_length = self.get_param("bb_length", 50)
        self.bb_mult = self.get_param("bb_mult", 2.0)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        """
        Phân tích dữ liệu giá để phát hiện xu hướng và đưa ra tín hiệu giao dịch.
        
        Args:
            symbol (str): Cặp giao dịch (ví dụ: BTC/USDT).
            ohlcv_data (list): Danh sách dữ liệu nến OHLCV.
            current_positions (list): Danh sách các vị thế đang mở hiện tại.
            
        Returns:
            StrategySignal: Tín hiệu giao dịch (Mở/Đóng LONG/SHORT hoặc không có tín hiệu).
        """
        # Khởi tạo DataFrame từ dữ liệu OHLCV
        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        if len(df) < max(self.slow_length, self.signal_length) * 2:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Not enough data")

        close_prices = df['close']

        # 1. Tính toán các đường trung bình động (Moving Averages)
        fast_ma = close_prices.rolling(self.fast_length).mean()
        slow_ma = close_prices.rolling(self.slow_length).mean()
        combined_ma = fast_ma + slow_ma
        smoothed_ma = combined_ma.rolling(self.signal_length).mean()

        # 2. Tính toán đường trung tâm và các dải băng (Bands)
        center_line = smoothed_ma / 2
        band_multiplier = 1
        band_base_width = 10
        log_width = np.log(band_base_width)
        
        band_up = center_line - (band_multiplier * log_width)
        band_dn = center_line + (band_multiplier * log_width)

        # Convert to numpy arrays for fast state machine simulation
        band_dn_arr = band_dn.to_numpy()
        band_up_arr = band_up.to_numpy()
        center_line_arr = center_line.to_numpy()
        
        trend_direction = np.zeros(len(df))
        high_bound = np.zeros(len(df))
        low_bound = np.zeros(len(df))
        high_limit = np.zeros(len(df))
        low_limit = np.zeros(len(df))

        # Find the first valid index to start processing
        first_valid_idx = np.where(~np.isnan(center_line_arr))[0]
        if len(first_valid_idx) == 0:
            return StrategySignal(signal="none", symbol=symbol, price=0, reason="Not enough valid data")
        
        start_idx = first_valid_idx[0]
        processed_count = 0
        
        # 3. Vòng lặp (State Machine) qua từng nến để xác định xu hướng (Trend Detection)
        for i in range(start_idx, len(df)):
            current_band_dn = band_dn_arr[i]
            current_band_up = band_up_arr[i]
            current_center = center_line_arr[i]
            
            if processed_count == 0:
                low_bound[i] = current_band_dn
                high_bound[i] = current_band_up
                low_limit[i] = current_center
                high_limit[i] = current_center
            elif processed_count == 1:
                if current_band_up >= high_bound[i-1]:
                    high_bound[i] = current_band_up
                    high_limit[i] = current_center
                    trend_direction[i] = 1
                else:
                    low_bound[i] = current_band_dn
                    low_limit[i] = current_center
                    trend_direction[i] = -1
            else:
                if trend_direction[i-1] > 0:
                    high_limit[i] = max(high_limit[i-1], current_center)
                    if current_band_up >= high_bound[i-1]:
                        high_bound[i] = current_band_up
                        trend_direction[i] = trend_direction[i-1] # Keep trend
                    else:
                        # Nếu giá phá vỡ dải băng trên quá mức factor, đảo chiều sang xu hướng giảm
                        if current_band_dn < high_bound[i-1] - high_bound[i-1] * self.trend_factor:
                            low_bound[i] = current_band_dn
                            low_limit[i] = current_center
                            trend_direction[i] = -1 # Trend reversal to downward
                        else:
                            high_bound[i] = high_bound[i-1]
                            low_bound[i] = low_bound[i-1]
                            trend_direction[i] = trend_direction[i-1]
                else:
                    low_limit[i] = min(low_limit[i-1], current_center)
                    if current_band_dn <= low_bound[i-1]:
                        low_bound[i] = current_band_dn
                        trend_direction[i] = trend_direction[i-1] # Keep trend
                    else:
                        # Nếu giá phá vỡ dải băng dưới quá mức factor, đảo chiều sang xu hướng tăng
                        if current_band_up > low_bound[i-1] + low_bound[i-1] * self.trend_factor:
                            high_bound[i] = current_band_up
                            high_limit[i] = current_center
                            trend_direction[i] = 1 # Trend reversal to upward
                        else:
                            high_bound[i] = high_bound[i-1]
                            low_bound[i] = low_bound[i-1]
                            trend_direction[i] = trend_direction[i-1]
            
            processed_count += 1

        current_trend = trend_direction[-1]
        prev_trend = trend_direction[-2]
        
        # 4. Tính toán phần Bollinger Bands và động lượng (Momentum) của SMA
        basis = close_prices.rolling(self.bb_length).mean()
        dev = close_prices.rolling(self.bb_length).std() * self.bb_mult
        upper_bb = basis + dev
        lower_bb = basis - dev
        
        momentum_state = "Chưa rõ"
        if len(basis) >= 3 and not pd.isna(basis.iloc[-3]):
            current_sma = basis.iloc[-1]
            prev_sma = basis.iloc[-2]
            older_sma = basis.iloc[-3]
            
            # Tính toán sự thay đổi giữa các kỳ (Tương đương sma21, sma10 trong Pine Script)
            diff_older_to_prev = older_sma - prev_sma
            diff_prev_to_curr = prev_sma - current_sma
            
            # Dự phóng giá trị SMA hiện tại theo nội suy tuyến tính (Tương đương sma0Hope)
            projected_current_sma = 2 * prev_sma - older_sma
            
            # Động lượng xu hướng: so sánh thực tế với dự phóng (Tương đương biến trend)
            momentum_diff = current_sma - projected_current_sma
            
            if momentum_diff == 0:
                momentum_state = "Vàng (Giữ nguyên xu hướng)"
            elif momentum_diff > 0:
                if diff_older_to_prev > 0:
                    if diff_prev_to_curr > 0:
                        momentum_state = "Cam (Giảm/Hãm độ dốc xuống)"
                    else:
                        momentum_state = "Tím (Đảo chiều tăng)"
                else:
                    momentum_state = "Xanh dương (Tăng độ dốc lên)"
            else:
                if diff_older_to_prev > 0:
                    momentum_state = "Đỏ (Tăng độ dốc xuống)"
                else:
                    if diff_prev_to_curr < 0:
                        momentum_state = "Xanh lá (Giảm/Hãm độ dốc lên)"
                    else:
                        momentum_state = "Tím (Đảo chiều giảm)"

        final_signal = "none"
        reason = f"Chờ tín hiệu | Momentum MA: {momentum_state}"
        
        # Crossover buy/sell signals
        if current_trend == 1 and prev_trend == -1:
            final_signal = "long"
            reason = f"Mở LONG: Custom SMA báo Trend Tăng | Momentum MA: {momentum_state}"
        elif current_trend == -1 and prev_trend == 1:
            final_signal = "short"
            reason = f"Mở SHORT: Custom SMA báo Trend Giảm | Momentum MA: {momentum_state}"

        current_price = close_prices.iloc[-1]

        # Check closing conditions for current positions
        for pos in current_positions:
            pos_symbol = pos.get("symbol", "").replace("/", "")
            if pos_symbol == symbol.replace("/", ""):
                side = pos.get("side", "")
                if side == "long" and current_trend == -1:
                    final_signal = "close_long"
                    reason = "Đóng LONG: Custom SMA báo Trend Giảm"
                elif side == "short" and current_trend == 1:
                    final_signal = "close_short"
                    reason = "Đóng SHORT: Custom SMA báo Trend Tăng"

        # Tạo siêu dữ liệu (metadata) để gửi ra frontend vẽ biểu đồ
        trend_plot_val = high_bound[-1] if current_trend == 1 else low_bound[-1] if current_trend == -1 else None
        trend_plot_color = "blue" if current_trend == 1 else "yellow"
        
        sma_line_color = "yellow"
        if len(basis) >= 2 and not pd.isna(basis.iloc[-2]):
            if current_sma > prev_sma:
                sma_line_color = "blue"
            elif current_sma < prev_sma:
                sma_line_color = "red"
                
        momentum_color = "yellow"
        if "Đỏ" in momentum_state: momentum_color = "red"
        elif "Cam" in momentum_state: momentum_color = "orange"
        elif "Xanh dương" in momentum_state: momentum_color = "blue"
        elif "Xanh lá" in momentum_state: momentum_color = "green"
        elif "Tím" in momentum_state: momentum_color = "purple"

        metadata = {
            "plots": [
                {
                    "name": "trend",
                    "value": float(trend_plot_val) if trend_plot_val is not None else None,
                    "color": trend_plot_color,
                    "style": "circles",
                    "linewidth": 1
                },
                {
                    "name": "SMA",
                    "value": float(current_sma) if not pd.isna(current_sma) else None,
                    "color": sma_line_color,
                    "style": "line",
                    "linewidth": 2
                },
                {
                    "name": "SMA-1",
                    "value": float(current_sma) if not pd.isna(current_sma) else None,
                    "color": momentum_color,
                    "style": "cross",
                    "linewidth": 3,
                    "tooltip": momentum_state
                }
            ],
            "bands": {
                "center_line": float(center_line_arr[-1]) if not pd.isna(center_line_arr[-1]) else None,
                "band_up": float(band_up_arr[-1]) if not pd.isna(band_up_arr[-1]) else None,
                "band_dn": float(band_dn_arr[-1]) if not pd.isna(band_dn_arr[-1]) else None
            }
        }

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason,
            metadata=metadata
        )
