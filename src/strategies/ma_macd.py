"""
ma_macd.py — MA + MACD Signal Strategy
Tạo tín hiệu Long/Short dựa trên:
  - MA Cross (Golden Cross / Death Cross)
  - MACD Cross (MACD vượt lên/xuống Signal Line)
"""
from loguru import logger
from src.data.indicators import (
    ohlcv_to_dataframe,
    get_ma_values,
    get_macd_values,
)
from .base_strategy import BaseStrategy, StrategySignal


class MaMacdStrategy(BaseStrategy):
    """
    MA + MACD Strategy
    ...
    """

    STRATEGY_NAME = "ma_macd"

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        """Lookback = max(ma_slow, macd_slow + macd_signal) + buffer."""
        ma_slow    = int(parameters.get("ma_slow",    26))
        macd_slow  = int(parameters.get("macd_slow",  26))
        macd_sig   = int(parameters.get("macd_signal", 9))
        return max(ma_slow, macd_slow + macd_sig) + 10

    async def prepare_metadata(self, df: "pd.DataFrame") -> dict:
        """Trả về MA và MACD values cho exit condition check."""
        try:
            from src.data.indicators import get_ma_values, get_macd_values
            ma   = get_ma_values(df, self.ma_fast, self.ma_slow, self.ma_type)
            macd = get_macd_values(df, self.macd_fast, self.macd_slow, self.macd_signal)
            meta: dict = {}
            if ma:
                meta.update({"ma_fast": ma.fast, "ma_slow": ma.slow,
                             "trend": 1 if ma.bullish else -1})
            if macd:
                meta.update({"macd": macd.macd, "macd_signal": macd.signal,
                             "macd_histogram": macd.histogram})
            return meta
        except Exception:
            return {}

    def __init__(self, config: dict):
        super().__init__(config)

        # MA params
        self.ma_fast = config.get("ma_fast", 12)
        self.ma_slow = config.get("ma_slow", 26)
        self.ma_type = config.get("ma_type", "EMA")

        # MACD params
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)

        # Logic: cần cả 2 điều kiện không?
        self.require_both = config.get("require_both_signals", True)

    async def analyze(self, symbol: str, ohlcv_data: list, current_positions: list) -> StrategySignal:
        """
        Phân tích OHLCV và trả về StrategySignal
        """
        no_signal = StrategySignal(signal="none", symbol=symbol, price=0, reason="No signal")

        # 1. Convert sang DataFrame
        df = ohlcv_to_dataframe(ohlcv_data)
        if len(df) < self.ma_slow + self.macd_slow + 5:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Không đủ dữ liệu lịch sử"
            )

        current_price = float(df["close"].iloc[-1])

        # 2. Tính MA values
        ma = get_ma_values(df, self.ma_fast, self.ma_slow, self.ma_type)
        if ma is None:
            return no_signal

        # 3. Tính MACD values
        macd = get_macd_values(df, self.macd_fast, self.macd_slow, self.macd_signal)
        if macd is None:
            return no_signal

        logger.debug(
            f"{symbol} | Price: {current_price:.4f} | "
            f"MA({self.ma_fast}): {ma.fast:.4f} MA({self.ma_slow}): {ma.slow:.4f} | "
            f"MACD: {macd.macd:.6f} Signal: {macd.signal:.6f}"
        )

        # 4. Kiểm tra vị thế hiện tại
        current_position = self._get_position(symbol, current_positions)
        has_long = current_position and current_position.get("side") == "long"
        has_short = current_position and current_position.get("side") == "short"

        # ─── Kiểm tra tín hiệu CLOSE ─────────────────────────────────────────

        # Đóng Long nếu xuất hiện Death Cross
        if has_long and ma.death_cross:
            return StrategySignal(
                signal="close_long",
                symbol=symbol,
                price=current_price,
                reason=f"Death Cross: MA{self.ma_fast} cắt xuống MA{self.ma_slow}",
            )

        # Đóng Short nếu xuất hiện Golden Cross
        if has_short and ma.golden_cross:
            return StrategySignal(
                signal="close_short",
                symbol=symbol,
                price=current_price,
                reason=f"Golden Cross: MA{self.ma_fast} vượt lên MA{self.ma_slow}",
            )

        # ─── Kiểm tra tín hiệu ENTRY ─────────────────────────────────────────

        # Không mở thêm vị thế nếu đã có
        if current_position:
            return StrategySignal(
                signal="none", symbol=symbol, price=current_price,
                reason="Đang có vị thế mở"
            )

        # Tín hiệu LONG
        long_signal = self._check_long_signal(ma, macd)
        if long_signal:
            reason = self._build_reason("LONG", ma, macd)
            logger.info(f"🟢 Signal LONG {symbol} @ {current_price:.4f} | {reason}")
            return StrategySignal(
                signal="long",
                symbol=symbol,
                price=current_price,
                reason=reason,
                confidence=self._calculate_confidence(ma, macd, "long"),
            )

        # Tín hiệu SHORT
        short_signal = self._check_short_signal(ma, macd)
        if short_signal:
            reason = self._build_reason("SHORT", ma, macd)
            logger.info(f"🔴 Signal SHORT {symbol} @ {current_price:.4f} | {reason}")
            return StrategySignal(
                signal="short",
                symbol=symbol,
                price=current_price,
                reason=reason,
                confidence=self._calculate_confidence(ma, macd, "short"),
            )

        return StrategySignal(
            signal="none", symbol=symbol, price=current_price,
            reason="Không có tín hiệu rõ ràng"
        )

    def _check_long_signal(self, ma, macd) -> bool:
        """Kiểm tra điều kiện vào Long"""
        ma_bullish = ma.golden_cross if self.require_both else ma.bullish
        macd_bullish = macd.bullish_cross and macd.is_positive
        
        if self.require_both:
            return ma.golden_cross and macd.bullish_cross and macd.is_positive
        else:
            return ma.bullish and macd.bullish_cross and macd.is_positive

    def _check_short_signal(self, ma, macd) -> bool:
        """Kiểm tra điều kiện vào Short"""
        if self.require_both:
            return ma.death_cross and macd.bearish_cross and macd.is_negative
        else:
            return ma.bearish and macd.bearish_cross and macd.is_negative

    def _get_position(self, symbol: str, positions: list) -> dict | None:
        """Tìm vị thế đang mở cho symbol"""
        for pos in positions:
            if pos.get("symbol") == symbol or pos.get("symbol", "").replace("/", "") == symbol.replace("/", ""):
                return pos
        return None

    def _calculate_confidence(self, ma, macd, direction: str) -> float:
        """Tính độ tin cậy của tín hiệu (0.0 - 1.0)"""
        score = 0.5  # Base score

        if direction == "long":
            if ma.golden_cross:
                score += 0.2
            if ma.bullish:
                score += 0.1
            if macd.bullish_cross:
                score += 0.1
            if macd.is_positive:
                score += 0.1
        else:
            if ma.death_cross:
                score += 0.2
            if ma.bearish:
                score += 0.1
            if macd.bearish_cross:
                score += 0.1
            if macd.is_negative:
                score += 0.1

        return min(score, 1.0)

    def _build_reason(self, direction: str, ma, macd) -> str:
        """Tạo mô tả lý do signal"""
        parts = []
        if direction == "LONG":
            if ma.golden_cross:
                parts.append(f"Golden Cross (MA{self.ma_fast}>{self.ma_slow})")
            if macd.bullish_cross:
                parts.append("MACD Cross Up")
            if macd.is_positive:
                parts.append(f"MACD={macd.macd:.5f}>0")
        else:
            if ma.death_cross:
                parts.append(f"Death Cross (MA{self.ma_fast}<{self.ma_slow})")
            if macd.bearish_cross:
                parts.append("MACD Cross Down")
            if macd.is_negative:
                parts.append(f"MACD={macd.macd:.5f}<0")
        return " | ".join(parts) if parts else direction
