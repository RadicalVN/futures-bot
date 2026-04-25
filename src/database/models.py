"""
models.py — SQLAlchemy ORM Models
Lưu trữ lịch sử giao dịch, tín hiệu, và trạng thái bot
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Enum
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    FAILED = "failed"


class SignalType(str, enum.Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    NONE = "none"


class Trade(Base):
    """Lịch sử các lệnh giao dịch"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Thông tin lệnh
    order_id = Column(String(100), unique=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)          # buy / sell
    order_type = Column(String(20), default="market")  # market / limit
    
    # Giá và số lượng
    amount = Column(Float, nullable=False)
    price = Column(Float)                  # Giá đặt lệnh
    avg_price = Column(Float)              # Giá thực tế khớp
    cost = Column(Float)                   # Tổng tiền
    fee = Column(Float, default=0)
    
    # Kết quả
    status = Column(String(20), default="pending")
    realized_pnl = Column(Float, default=0)
    
    # Context
    strategy = Column(String(50), default="ma_macd")
    signal_type = Column(String(20))       # long / short / close_long / close_short
    leverage = Column(Integer, default=1)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)
    
    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "amount": self.amount,
            "price": self.price,
            "avg_price": self.avg_price,
            "cost": self.cost,
            "fee": self.fee,
            "status": self.status,
            "realized_pnl": self.realized_pnl,
            "strategy": self.strategy,
            "signal_type": self.signal_type,
            "leverage": self.leverage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class Signal(Base):
    """Lịch sử các tín hiệu được tạo ra bởi strategy"""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    signal_type = Column(String(20), nullable=False)   # long / short / none
    
    # Giá trị indicator tại thời điểm signal
    price = Column(Float)
    ma_fast = Column(Float)
    ma_slow = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_histogram = Column(Float)
    
    # Signal có được thực thi không?
    executed = Column(Boolean, default=False)
    execution_reason = Column(Text)        # Lý do không thực thi (nếu có)
    
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "price": self.price,
            "ma_fast": self.ma_fast,
            "ma_slow": self.ma_slow,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "executed": self.executed,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class BotStatus(Base):
    """Trạng thái bot — chỉ có 1 row"""
    __tablename__ = "bot_status"

    id = Column(Integer, primary_key=True, default=1)
    is_running = Column(Boolean, default=False)
    mode = Column(String(20), default="testnet")       # testnet / mainnet
    active_strategy = Column(String(50), default="ma_macd")
    
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0)
    
    started_at = Column(DateTime)
    last_signal_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        win_rate = (
            round(self.winning_trades / self.total_trades * 100, 2)
            if self.total_trades > 0 else 0
        )
        return {
            "is_running": self.is_running,
            "mode": self.mode,
            "active_strategy": self.active_strategy,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": round(self.total_pnl, 4),
            "win_rate": win_rate,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_signal_at": self.last_signal_at.isoformat() if self.last_signal_at else None,
        }
