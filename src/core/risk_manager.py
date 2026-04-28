"""
risk_manager.py — Risk Management
Tính toán position size, stop loss, take profit
"""
from dataclasses import dataclass
from loguru import logger


@dataclass
class PositionPlan:
    """Kế hoạch cho một lệnh"""
    symbol: str
    side: str          # "buy" (Long) hoặc "sell" (Short)
    amount: float      # Số lượng contract
    entry_price: float
    stop_loss: float
    take_profit: float
    leverage: int
    usdt_value: float  # Giá trị USDT của position
    risk_amount: float # Số USDT có thể mất (nếu hit SL)


class RiskManager:
    """
    Quản lý rủi ro cho từng lệnh giao dịch
    """

    def __init__(self, config: dict):
        self.leverage = config.get("leverage", 5)
        self.position_size_pct = config.get("position_size_pct", 0.10)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.take_profit_pct = config.get("take_profit_pct", 0.04)
        self.trailing_stop_enabled = config.get("trailing_stop_enabled", False)
        self.trailing_activation_pct = config.get("trailing_stop_activation_pct", 0.02)
        self.trailing_callback_pct = config.get("trailing_stop_callback_pct", 0.01)
        self.max_open_positions = config.get("max_open_positions", 2)

    def calculate_position(
        self,
        balance_usdt: float,
        entry_price: float,
        side: str,
        symbol: str,
        contract_size: float = 1.0,
        min_amount: float = 0.001,
        amount_precision: int = 3,
    ) -> PositionPlan | None:
        """
        Tính toán kế hoạch lệnh đầy đủ
        
        Args:
            balance_usdt: Số dư USDT hiện tại
            entry_price: Giá vào lệnh
            side: "buy" (Long) hoặc "sell" (Short)
            symbol: Symbol trading
            contract_size: Kích thước 1 contract
            min_amount: Số lượng tối thiểu
            amount_precision: Độ chính xác số lượng
        """
        if balance_usdt <= 0:
            logger.error("Số dư USDT = 0, không thể tạo lệnh")
            return None

        # Số USDT phân bổ cho lệnh này (không tính leverage)
        allocated_usdt = balance_usdt * self.position_size_pct
        
        # Giá trị position thực tế (có leverage)
        position_value = allocated_usdt * self.leverage
        
        # Số lượng contract
        amount = position_value / (entry_price * contract_size)
        
        # Làm tròn theo precision của exchange
        amount = round(amount, int(amount_precision))
        
        if amount < min_amount:
            logger.warning(
                f"Amount {amount} < min_amount {min_amount} cho {symbol}. "
                f"Số dư có thể quá nhỏ."
            )
            return None

        # Tính SL và TP
        sl_price, tp_price = self._calculate_sl_tp(entry_price, side)

        # Ước tính risk amount (nếu hit SL)
        risk_amount = allocated_usdt * self.stop_loss_pct * self.leverage

        plan = PositionPlan(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            leverage=self.leverage,
            usdt_value=position_value,
            risk_amount=risk_amount,
        )

        logger.info(
            f"📊 Position Plan [{symbol}] {side.upper()} | "
            f"Amount: {amount} | Entry: {entry_price:.4f} | "
            f"SL: {sl_price:.4f} | TP: {tp_price:.4f} | "
            f"Leverage: {self.leverage}x | Risk: ${risk_amount:.2f}"
        )

        return plan

    def _calculate_sl_tp(self, entry_price: float, side: str) -> tuple[float, float]:
        """Tính giá Stop Loss và Take Profit"""
        if side == "buy":  # Long
            sl = entry_price * (1 - self.stop_loss_pct)
            tp = entry_price * (1 + self.take_profit_pct)
        else:  # Short
            sl = entry_price * (1 + self.stop_loss_pct)
            tp = entry_price * (1 - self.take_profit_pct)

        return round(sl, 8), round(tp, 8)

    def should_stop_loss(self, entry_price: float, current_price: float, side: str) -> bool:
        """Kiểm tra có nên đóng lệnh theo SL không"""
        sl, _ = self._calculate_sl_tp(entry_price, side)
        if side == "buy":
            return current_price <= sl
        else:
            return current_price >= sl

    def should_take_profit(self, entry_price: float, current_price: float, side: str) -> bool:
        """Kiểm tra có nên đóng lệnh theo TP không"""
        _, tp = self._calculate_sl_tp(entry_price, side)
        if side == "buy":
            return current_price >= tp
        else:
            return current_price <= tp

    def check_max_positions(self, open_positions: list) -> bool:
        """Kiểm tra có còn slot để mở vị thế mới không"""
        return len(open_positions) < self.max_open_positions

    def calculate_trailing_stop(
        self, entry_price: float, current_price: float, side: str
    ) -> float | None:
        """
        Tính trailing stop price
        Returns: None nếu chưa đến ngưỡng kích hoạt
        """
        if not self.trailing_stop_enabled:
            return None

        if side == "buy":
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct >= self.trailing_activation_pct:
                return current_price * (1 - self.trailing_callback_pct)
        else:
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct >= self.trailing_activation_pct:
                return current_price * (1 + self.trailing_callback_pct)

        return None
