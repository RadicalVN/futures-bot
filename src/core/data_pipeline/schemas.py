from enum import Enum
from datetime import datetime
from pydantic import BaseModel

class AssetClass(str, Enum):
    CRYPTO = "CRYPTO"
    FOREX  = "FOREX"
    STOCKS = "STOCKS"

class TradingSession(str, Enum):
    OPEN       = "OPEN"
    CLOSED     = "CLOSED"
    PRE_MARKET = "PRE_MARKET"

class IntegrityStatus(str, Enum):
    PASS            = "PASS"
    BLOCK_GAP       = "BLOCK_GAP"
    BLOCK_WARMUP    = "BLOCK_WARMUP"
    BLOCK_OUTLIER   = "BLOCK_OUTLIER"

class Candle1m(BaseModel):
    symbol:    str
    open_time: datetime
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float

class ResampledCandle(BaseModel):
    symbol:     str
    timeframe:  str       # "5m", "15m", "1h", …
    open_time:  datetime
    close_time: datetime
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     float

class AdapterConfig(BaseModel):
    asset_class:       AssetClass
    outlier_threshold: float              # Ngưỡng động theo loại tài sản
    symbol_overrides:  dict[str, float] = {}  # Override theo từng symbol

class HealGapEvent(BaseModel):
    symbol:     str
    gap_start:  datetime
    gap_end:    datetime
    attempt_no: int = 1

class IntegrityCheckResult(BaseModel):
    is_valid:    bool
    status:      IntegrityStatus
    reason:      str | None       = None
    symbol:      str
    checked_at:  datetime
    heal_event:  HealGapEvent | None = None  # Chỉ có khi status=BLOCK_GAP
