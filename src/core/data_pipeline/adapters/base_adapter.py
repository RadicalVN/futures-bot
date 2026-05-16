from abc import ABC, abstractmethod
from datetime import datetime
from src.core.data_pipeline.schemas import Candle1m, TradingSession, AdapterConfig

class BaseSessionAdapter(ABC):
    """Hợp đồng interface bắt buộc cho mọi Data Adapter.

    Mọi concrete adapter (BinanceAdapter, CSVAdapter, ForexAdapter)
    đều phải implement đầy đủ 5 abstract methods này.
    """

    @abstractmethod
    async def fetch_latest_1m_candles(
        self, symbol: str, limit: int
    ) -> list[Candle1m]: ...

    @abstractmethod
    async def fetch_gap_candles(
        self, symbol: str, since: datetime, until: datetime
    ) -> list[Candle1m]:
        """Lấy bù dữ liệu trong khoảng Gap — phục vụ Self-Healing Pipeline."""
        ...

    @abstractmethod
    def get_current_session(self) -> TradingSession: ...

    @abstractmethod
    def is_tradeable_now(self) -> bool: ...

    @abstractmethod
    def get_adapter_config(self) -> AdapterConfig:
        """Trả về config động cho asset class, bao gồm outlier_threshold."""
        ...
