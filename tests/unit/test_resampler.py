import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from src.core.data_pipeline.schemas import Candle1m
from src.core.data_pipeline.resampler import CandleResampler

def test_resample_5m():
    """Kiểm tra gộp 5 nến 1m thành 1 nến 5m chính xác."""
    base_time = datetime(2026, 5, 17, 7, 0, tzinfo=timezone.utc)
    
    candles_1m = [
        Candle1m(symbol="BTC", open_time=base_time, open=100, high=105, low=95, close=102, volume=10),
        Candle1m(symbol="BTC", open_time=base_time + timedelta(minutes=1), open=102, high=108, low=101, close=106, volume=15),
        Candle1m(symbol="BTC", open_time=base_time + timedelta(minutes=2), open=106, high=110, low=105, close=109, volume=20),
        Candle1m(symbol="BTC", open_time=base_time + timedelta(minutes=3), open=109, high=112, low=107, close=108, volume=25),
        Candle1m(symbol="BTC", open_time=base_time + timedelta(minutes=4), open=108, high=109, low=100, close=101, volume=30),
    ]
    
    resampled = CandleResampler.resample(candles_1m, "5m")
    
    assert len(resampled) == 1
    c5 = resampled[0]
    
    assert c5.symbol == "BTC"
    assert c5.open == 100
    assert c5.high == 112
    assert c5.low == 95
    assert c5.close == 101
    assert c5.volume == 100

def test_resample_cross_boundary():
    """Kiểm tra nến rải rác qua 2 bucket thời gian (cross boundary)."""
    base_time = datetime(2026, 5, 17, 7, 4, tzinfo=timezone.utc)
    
    candles_1m = [
        # Bucket 1: 07:00 - 07:05 (chỉ có phút 04)
        Candle1m(symbol="ETH", open_time=base_time, open=2000, high=2010, low=1990, close=2005, volume=5),
        # Bucket 2: 07:05 - 07:10 (phút 05, 06)
        Candle1m(symbol="ETH", open_time=base_time + timedelta(minutes=1), open=2005, high=2020, low=2000, close=2015, volume=10),
        Candle1m(symbol="ETH", open_time=base_time + timedelta(minutes=2), open=2015, high=2025, low=2010, close=2020, volume=10),
    ]
    
    resampled = CandleResampler.resample(candles_1m, "5m")
    
    assert len(resampled) == 2
    # Bucket 1
    assert resampled[0].open_time == datetime(2026, 5, 17, 7, 0, tzinfo=timezone.utc)
    assert resampled[0].close == 2005
    assert resampled[0].volume == 5
    
    # Bucket 2
    assert resampled[1].open_time == datetime(2026, 5, 17, 7, 5, tzinfo=timezone.utc)
    assert resampled[1].high == 2025
    assert resampled[1].volume == 20

def test_resample_with_timezone():
    """Kiểm tra Pandas resample không làm sai lệch timezone."""
    # Múi giờ Asia/Tokyo (+09:00)
    base_time = datetime(2026, 5, 17, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    
    candles_1m = [
        Candle1m(symbol="SOL", open_time=base_time, open=10, high=12, low=9, close=11, volume=100),
        Candle1m(symbol="SOL", open_time=base_time + timedelta(minutes=1), open=11, high=13, low=10, close=12, volume=200),
    ]
    
    resampled = CandleResampler.resample(candles_1m, "5m")
    
    assert len(resampled) == 1
    c5 = resampled[0]
    
    assert c5.open_time.tzinfo is not None
    assert c5.open_time == datetime(2026, 5, 17, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert c5.close_time == datetime(2026, 5, 17, 10, 5, tzinfo=ZoneInfo("Asia/Tokyo"))

def test_resample_multiple_symbols_raises_error():
    """Kiểm tra chốt chặn phòng thủ: Resampler từ chối gộp nến của nhiều Symbol cùng lúc."""
    base_time = datetime(2026, 5, 17, 7, 0, tzinfo=timezone.utc)
    
    candles_1m = [
        Candle1m(symbol="BTC", open_time=base_time, open=100, high=105, low=95, close=102, volume=10),
        Candle1m(symbol="ETH", open_time=base_time + timedelta(minutes=1), open=2000, high=2010, low=1990, close=2005, volume=15),
    ]
    
    with pytest.raises(ValueError, match="CandleResampler chỉ xử lý danh sách nến của MỘT symbol duy nhất trong mỗi lượt gọi."):
        CandleResampler.resample(candles_1m, "5m")
