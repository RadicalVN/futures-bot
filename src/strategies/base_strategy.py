"""
base_strategy.py — Abstract Base Class cho tất cả strategies
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategySignal:
    """Kết quả tín hiệu từ strategy"""
    signal: str          # "long", "short", "close_long", "close_short", "none"
    symbol: str
    price: float
    reason: str          # Lý do tạo tín hiệu
    confidence: float = 1.0  # 0.0 → 1.0

    @property
    def is_entry(self) -> bool:
        return self.signal in ("long", "short")

    @property
    def is_exit(self) -> bool:
        return self.signal in ("close_long", "close_short")

    @property
    def is_none(self) -> bool:
        return self.signal == "none"


class BaseStrategy(ABC):
    """Abstract base class — mọi strategy đều kế thừa từ đây"""

    def __init__(self, config: dict):
        self.config = config
        self.name = "base"

    @abstractmethod
    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        """
        Phân tích dữ liệu và trả về tín hiệu
        Subclass bắt buộc phải implement method này
        """
        pass

    def get_param(self, key: str, default=None):
        """Helper lấy parameter từ config"""
        return self.config.get(key, default)
