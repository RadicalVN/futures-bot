"""
base_strategy.py — Self-Contained Contract cho tất cả Strategy.

Mỗi Strategy phải là một "Plugin" hoàn chỉnh:
  - Khai báo định danh (STRATEGY_NAME)
  - Tự tính số nến cần thiết (get_required_lookback)
  - Tự tính metadata indicators (prepare_metadata)
  - Khai báo hành vi đặc biệt (requires_one_shot_check)

Nguyên tắc Zero-Core-Edit:
  Thêm strategy mới = tạo 1 file .py, không sửa bất kỳ file core nào.
  BotEngine và ExitMonitorService không biết gì về strategy cụ thể.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class StrategySignal:
    """Kết quả tín hiệu từ strategy.

    Attributes:
        signal: Loại tín hiệu — "long" | "short" | "close_long" | "close_short" | "none".
        symbol: Symbol giao dịch (vd: "BTC/USDT").
        price: Giá tại thời điểm tín hiệu.
        reason: Mô tả lý do tạo tín hiệu (dùng cho log và Discord).
        confidence: Độ tin cậy 0.0 → 1.0 (dùng cho AI filter).
        metadata: Dữ liệu phụ trợ — indicators, colors, phase timestamps, ...
    """
    signal:     str
    symbol:     str
    price:      float
    reason:     str
    confidence: float = 1.0
    metadata:   Optional[dict] = None

    @property
    def is_entry(self) -> bool:
        """True nếu là tín hiệu mở lệnh mới."""
        return self.signal in ("long", "short")

    @property
    def is_exit(self) -> bool:
        """True nếu là tín hiệu đóng lệnh."""
        return self.signal in ("close_long", "close_short")

    @property
    def is_none(self) -> bool:
        """True nếu không có tín hiệu."""
        return self.signal == "none"


class BaseStrategy(ABC):
    """Abstract base class — Self-Contained Contract cho mọi strategy.

    Mỗi subclass PHẢI:
      1. Khai báo ``STRATEGY_NAME`` (str, không rỗng).
      2. Implement ``analyze()`` — logic giao dịch chính.

    Mỗi subclass NÊN override (có default hợp lý):
      3. ``get_required_lookback()`` — số nến tối thiểu.
      4. ``prepare_metadata()`` — tính indicators cho ExitMonitorService.
      5. ``requires_one_shot_check`` — bật nếu cần giới hạn 1 lệnh/phase.

    Example — thêm strategy mới (không cần sửa file nào khác):
        class MyNewStrategy(BaseStrategy):
            STRATEGY_NAME = "my_new_strategy"

            @classmethod
            def get_required_lookback(cls, parameters: dict) -> int:
                return int(parameters.get("period", 100)) + 50

            async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
                return {"trend": ..., "momentum": ...}

            async def analyze(self, symbol, ohlcv_data, current_positions):
                ...
    """

    # ── Class-level contract attributes ──────────────────────────────────────

    STRATEGY_NAME: str = ""
    """Định danh duy nhất của strategy.

    Phải là string không rỗng, khớp với giá trị lưu trong Bot.strategy_name.
    StrategyFactory dùng field này để build registry tự động.

    Example:
        STRATEGY_NAME = "sma_macd_cross_v7"
    """

    PARAMETERS_SCHEMA: dict = {}
    """JSON Schema (Draft-7 subset) mô tả các tham số của strategy.

    Dùng để Dashboard tự động render form nhập liệu — không cần hardcode
    field nào trong frontend. Mỗi property tuân theo JSON Schema chuẩn
    với extension ``ui:widget`` để frontend biết loại input cần render.

    Supported ``ui:widget`` values:
        - ``"number"``  : <input type="number">
        - ``"select"``  : <select> với options từ ``enum``
        - ``"boolean"`` : <input type="checkbox">
        - ``"text"``    : <input type="text">

    Example:
        PARAMETERS_SCHEMA = {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "title": "Timeframe",
                    "description": "Khung thoi gian nen",
                    "default": "5m",
                    "enum": ["1m","3m","5m","15m","30m","1h","4h","1d"],
                    "ui:widget": "select",
                },
                "ma_fast": {
                    "type": "integer",
                    "title": "MA Fast Period",
                    "description": "Chu ky MA nhanh",
                    "default": 12,
                    "minimum": 1,
                    "maximum": 500,
                    "ui:widget": "number",
                },
            },
        }

    Default: {} — strategy chua khai bao schema, UI dung raw JSON editor.
    """

    requires_one_shot_check: bool = False
    """Bật nếu strategy chỉ cho phép 1 lệnh mỗi phase Signal.

    Khi True, BotEngine sẽ tự động gọi ``_check_one_shot_phase()``
    trước khi đặt lệnh — không cần hardcode tên strategy trong Engine.

    Các strategy sma_macd_cross (v1-v7) override thành True vì mỗi
    phase Signal bullish/bearish chỉ được vào 1 lệnh duy nhất.

    Default: False — hầu hết strategy không cần giới hạn này.
    """

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(self, config: dict) -> None:
        """Khởi tạo strategy với config dict từ Bot.parameters.

        Args:
            config: Dict tham số từ Bot.parameters trong DB.
        """
        self.config = config
        # Backward compat: một số code cũ dùng self.name
        self.name = self.STRATEGY_NAME or "base"

    # ── Class methods (không cần instance) ───────────────────────────────────

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        """Tính số nến tối thiểu cần thiết dựa trên tham số.

        Strategy tự tính lookback của nó — BotEngine không cần biết
        chi tiết về từng strategy. Đây là phần thay thế cho logic
        if/elif tính lookback trong BotEngine.initialize().

        Args:
            parameters: Dict tham số từ Bot.parameters.

        Returns:
            Số nến tối thiểu. BotEngine sẽ dùng max(config_lookback, này).

        Example (sma_macd_cross):
            @classmethod
            def get_required_lookback(cls, parameters: dict) -> int:
                signal_len = int(parameters.get("macd_signal_length", 500))
                return signal_len + 50

        Example (adts):
            @classmethod
            def get_required_lookback(cls, parameters: dict) -> int:
                bbwidth_sma = int(parameters.get("bbwidth_sma_period", 200))
                return bbwidth_sma * 10 + 100
        """
        return 200  # Default an toàn cho hầu hết strategy

    # ── Instance methods ──────────────────────────────────────────────────────

    @abstractmethod
    async def analyze(
        self,
        symbol:            str,
        ohlcv_data:        list,
        current_positions: list,
    ) -> StrategySignal:
        """Phân tích dữ liệu và trả về tín hiệu giao dịch.

        Đây là method bắt buộc — mọi strategy phải implement.

        Args:
            symbol: Symbol giao dịch (vd: "BTC/USDT").
            ohlcv_data: List [[timestamp_ms, open, high, low, close, volume], ...].
            current_positions: List vị thế đang mở từ exchange.

        Returns:
            StrategySignal với signal, price, reason, metadata.
        """

    async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
        """Tính toán indicators và trả về metadata dict.

        Được gọi bởi ExitMonitorService để kiểm tra exit condition
        mà không cần biết strategy cụ thể là gì.

        Strategy tự quyết định cần tính indicator nào. ExitMonitorService
        chỉ nhận dict kết quả và truyền vào ``_check_exit_condition()``.

        Args:
            df: DataFrame OHLCV với columns [timestamp, open, high, low, close, volume].
                Đã được fetch từ exchange với đủ lookback.

        Returns:
            Dict metadata chứa các giá trị indicator cần thiết cho exit check.
            Ví dụ: {"trend": 1, "momentum": "blue", "slope_pct": 0.05, ...}
            Trả về {} nếu strategy không cần metadata đặc biệt.

        Example (sma_macd_cross):
            async def prepare_metadata(self, df):
                df = add_custom_sma_to_df(df)
                df = add_custom_macd_to_df(df, ...)
                return {
                    "ma_color": ..., "sig_color": ...,
                    "ma": ..., "macd": ..., "close": ...,
                }

        Example (adts):
            async def prepare_metadata(self, df):
                snap = build_indicator_snapshot(df, ...)
                return {"adx": snap.adx, "bb_width": snap.bb_width, ...}
        """
        return {}  # Default: không cần metadata đặc biệt

    # ── Helper ────────────────────────────────────────────────────────────────

    def get_param(self, key: str, default=None):
        """Helper lấy parameter từ config với fallback.

        Args:
            key: Tên tham số.
            default: Giá trị mặc định nếu không tìm thấy.

        Returns:
            Giá trị tham số hoặc default.
        """
        return self.config.get(key, default)
