import pandas as pd
from typing import List
from src.core.data_pipeline.schemas import Candle1m, ResampledCandle

class CandleResampler:
    """Module In-Memory Resampler sử dụng Pandas để gộp nến 1m."""

    @staticmethod
    def _get_pandas_freq(timeframe: str) -> str:
        """Chuyển đổi timeframe hệ thống sang định dạng Frequency của Pandas."""
        if timeframe.endswith("m"):
            return timeframe.replace("m", "min")
        if timeframe.endswith("h"):
            return timeframe
        if timeframe.endswith("d"):
            return timeframe.replace("d", "D")
        raise ValueError(f"Khung thời gian không được hỗ trợ: {timeframe}")

    @staticmethod
    def resample(candles: List[Candle1m], timeframe: str) -> List[ResampledCandle]:
        """Tổng hợp danh sách nến 1m thành nến ResampledCandle sử dụng Pandas.
        
        Quy tắc gộp (OHLCV):
        - open/close: first/last.
        - high/low: max/min.
        - volume: sum.
        
        Args:
            candles (List[Candle1m]): Danh sách nến 1m đầu vào.
            timeframe (str): Khung thời gian đích (vd: '5m').
            
        Returns:
            List[ResampledCandle]: Danh sách nến sau khi gộp.
        """
        if not candles:
            return []

        # Chuyển đổi thành DataFrame với DatetimeIndex để tối ưu Pandas
        data = [{
            "symbol": c.symbol,
            "open_time": c.open_time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        } for c in candles]
        
        df = pd.DataFrame(data)
        
        # Chốt chặn phòng thủ kiến trúc: Ngăn chặn xử lý trộn lẫn dữ liệu nhiều mã giao dịch
        if not df.empty and df["symbol"].nunique() > 1:
            raise ValueError("CandleResampler chỉ xử lý danh sách nến của MỘT symbol duy nhất trong mỗi lượt gọi.")
            
        df.set_index("open_time", inplace=True)
        
        # Áp dụng hàm resample() và agg() của Pandas
        freq = CandleResampler._get_pandas_freq(timeframe)
        resampled_df = df.resample(freq).agg({
            "symbol": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()
        
        # Build lại danh sách ResampledCandle
        result = []
        td = pd.to_timedelta(freq)
        
        for idx, row in resampled_df.iterrows():
            result.append(ResampledCandle(
                symbol=row["symbol"],
                timeframe=timeframe,
                open_time=idx.to_pydatetime(),
                close_time=(idx + td).to_pydatetime(),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"]
            ))
            
        return result
