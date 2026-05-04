import pandas as pd
from src.strategies.base_strategy import BaseStrategy, StrategySignal

class CustomMACDStrategy(BaseStrategy):
    """
    Chiến thuật dựa trên chỉ báo MACD Custom (MACD-TuanTV1008)
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "custom_macd"
        self.fast_length = self.get_param("fast_length", 12)
        self.slow_length = self.get_param("slow_length", 26)
        self.signal_length = self.get_param("signal_length", 500)
        self.sma_source = self.get_param("sma_source", "EMA")  # "SMA" or "EMA"
        self.sma_signal = self.get_param("sma_signal", "EMA")  # "SMA" or "EMA"

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        
        # MACD Custom này dùng signal_length tới 500 nên cần rất nhiều nến
        required_len = max(self.slow_length, self.signal_length) + 10
        if len(df) < required_len:
            # Sẽ cần config lookback lớn hơn
            pass # Vẫn tính nhưng có thể bị NaN ở các giá trị đầu

        close = df['close']

        if self.sma_source == "SMA":
            fast_ma = close.rolling(self.fast_length).mean()
            slow_ma = close.rolling(self.slow_length).mean()
        else:
            fast_ma = close.ewm(span=self.fast_length, adjust=False).mean()
            slow_ma = close.ewm(span=self.slow_length, adjust=False).mean()

        macd = fast_ma - slow_ma

        if self.sma_signal == "SMA":
            signal_line = macd.rolling(self.signal_length).mean()
        else:
            signal_line = macd.ewm(span=self.signal_length, adjust=False).mean()

        macd_curr = macd.iloc[-1]
        macd_prev = macd.iloc[-2]
        sig_curr = signal_line.iloc[-1]
        sig_prev = signal_line.iloc[-2]

        final_signal = "none"
        reason = "Chờ tín hiệu giao cắt MACD"

        # Tín hiệu Mua (MACD cắt lên Signal)
        if macd_prev <= sig_prev and macd_curr > sig_curr:
            final_signal = "long"
            reason = "Mở LONG: Custom MACD cắt lên đường Signal"
        
        # Tín hiệu Bán (MACD cắt xuống Signal)
        elif macd_prev >= sig_prev and macd_curr < sig_curr:
            final_signal = "short"
            reason = "Mở SHORT: Custom MACD cắt xuống đường Signal"

        current_price = close.iloc[-1]

        # Quản lý đóng lệnh
        for pos in current_positions:
            pos_symbol = pos.get("symbol", "").replace("/", "")
            if pos_symbol == symbol.replace("/", ""):
                side = pos.get("side", "")
                if side == "long" and final_signal == "short":
                    # Thay vì mở short luôn, ta có thể chỉ đóng lệnh Long (tùy quản lý rủi ro)
                    # Ở đây cho phép đảo chiều hoặc đóng
                    final_signal = "close_long"
                    reason = "Chốt lệnh LONG: Custom MACD báo tín hiệu Bán"
                elif side == "short" and final_signal == "long":
                    final_signal = "close_short"
                    reason = "Chốt lệnh SHORT: Custom MACD báo tín hiệu Mua"

        return StrategySignal(
            signal=final_signal,
            symbol=symbol,
            price=current_price,
            reason=reason
        )