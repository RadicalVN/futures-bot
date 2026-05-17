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
    ) -> list[Candle1m]:
        """Lấy danh sách các nến 1m gần nhất từ sàn giao dịch.

        Args:
            symbol (str): Mã giao dịch (ví dụ: BTCUSDT).
            limit (int): Số lượng nến tối đa cần lấy.

        Returns:
            list[Candle1m]: Danh sách nến 1m theo thứ tự thời gian.
            
        Raises:
            ConnectionError: Nếu không kết nối được với API sàn.
        """
        ...

    @abstractmethod
    async def fetch_gap_candles(
        self, symbol: str, since: datetime, until: datetime
    ) -> list[Candle1m]:
        """Lấy bù dữ liệu trong khoảng Gap — phục vụ Self-Healing Pipeline.

        Args:
            symbol (str): Mã giao dịch (ví dụ: BTCUSDT).
            since (datetime): Thời điểm bắt đầu của khoảng Gap.
            until (datetime): Thời điểm kết thúc của khoảng Gap.

        Returns:
            list[Candle1m]: Danh sách nến 1m lấp đầy khoảng Gap.
            
        Raises:
            ValueError: Nếu 'since' lớn hơn hoặc bằng 'until'.
            ConnectionError: Nếu không kết nối được với API sàn.
        """
        ...

    @abstractmethod
    def get_current_session(self) -> TradingSession:
        """Kiểm tra trạng thái phiên giao dịch hiện tại của tài sản.

        Returns:
            TradingSession: Trạng thái phiên hiện tại (OPEN, CLOSED, PRE_MARKET).
        """
        ...

    @abstractmethod
    def is_tradeable_now(self) -> bool:
        """Kiểm tra xem hệ thống có được phép giao dịch tại thời điểm hiện tại hay không.

        Bao gồm việc kiểm tra Circuit Breaker, Session Status, và các điều kiện an toàn khác.

        Returns:
            bool: True nếu có thể giao dịch, False nếu ngược lại.
        """
        ...

    @abstractmethod
    def get_adapter_config(self) -> AdapterConfig:
        """Trả về config động cho asset class, bao gồm outlier_threshold.

        Returns:
            AdapterConfig: Cấu hình của adapter được gán cho loại tài sản cụ thể.
        """
        ...
