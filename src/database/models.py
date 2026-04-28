"""
models.py — SQLAlchemy ORM Models
Cấu trúc Database chuyên nghiệp cho Nền tảng Bot Trading
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
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


class ExchangeAccount(Base):
    """Quản lý các tài khoản API giao dịch của người dùng"""
    __tablename__ = "exchange_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)           # vd: Tài khoản Binance Chính
    exchange_id = Column(String(50), default="binance")  # binance, okx, bybit...
    api_key = Column(String(255), nullable=True)         # Có thể mã hóa ở tầng logic
    api_secret = Column(String(255), nullable=True)
    mode = Column(String(20), default="testnet")         # testnet / mainnet
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    bots = relationship("Bot", back_populates="account")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "exchange_id": self.exchange_id,
            "mode": self.mode,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Bot(Base):
    """Bảng quản lý danh sách các Bot"""
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Liên kết với API Key nào
    account_id = Column(Integer, ForeignKey("exchange_accounts.id"), nullable=True)
    account = relationship("ExchangeAccount", back_populates="bots")
    
    name = Column(String(100), nullable=False)
    symbols = Column(JSON, default=["BTCUSDT"])             # vd: ["BTCUSDT", "ETHUSDT"] hoặc ["ALL"]
    strategy_name = Column(String(50), nullable=False)      # vd: ma_macd
    status = Column(String(20), default="stopped")          # running, stopped, error
    
    # Soft Delete để không mất lịch sử giao dịch khi xóa bot
    is_deleted = Column(Boolean, default=False)
    
    # Lưu các tham số tùy chỉnh của chiến thuật
    parameters = Column(JSON, default={})
    
    # Thống kê PnL
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Quan hệ
    trades = relationship("Trade", back_populates="bot", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="bot", cascade="all, delete-orphan")
    events = relationship("BotEvent", back_populates="bot", cascade="all, delete-orphan")

    def to_dict(self):
        win_rate = (
            round(self.winning_trades / self.total_trades * 100, 2)
            if self.total_trades > 0 else 0
        )
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": self.name,
            "symbols": self.symbols,
            "strategy_name": self.strategy_name,
            "status": self.status,
            "is_deleted": self.is_deleted,
            "parameters": self.parameters,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": round(self.total_pnl, 4),
            "win_rate": win_rate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BotEvent(Base):
    """Nhật ký hoạt động của bot để hiển thị lên Web UI"""
    __tablename__ = "bot_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    bot = relationship("Bot", back_populates="events")
    
    level = Column(String(20), default="info")  # info, warning, error, success
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class Trade(Base):
    """Lịch sử các lệnh giao dịch"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=True)
    bot = relationship("Bot", back_populates="trades")
    
    order_id = Column(String(100), unique=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)          
    order_type = Column(String(20), default="market")  
    
    amount = Column(Float, nullable=False)
    price = Column(Float)
    avg_price = Column(Float)
    cost = Column(Float)
    fee = Column(Float, default=0)
    
    status = Column(String(20), default="pending")
    realized_pnl = Column(Float, default=0)
    
    strategy = Column(String(50))
    signal_type = Column(String(20))
    leverage = Column(Integer, default=1)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)
    
    def to_dict(self):
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "amount": self.amount,
            "price": self.price,
            "avg_price": self.avg_price,
            "cost": round(self.cost, 4) if self.cost else None,
            "fee": round(self.fee, 6) if self.fee else 0,
            "status": self.status,
            "realized_pnl": round(self.realized_pnl, 4) if self.realized_pnl else 0,
            "strategy": self.strategy,
            "signal_type": self.signal_type,
            "leverage": self.leverage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class Signal(Base):
    """Lịch sử tín hiệu Indicator sinh ra"""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=True)
    bot = relationship("Bot", back_populates="signals")

    symbol = Column(String(20), index=True)
    signal_type = Column(String(20))
    price = Column(Float)
    
    ma_fast = Column(Float)
    ma_slow = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_histogram = Column(Float)
    
    executed = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "executed": self.executed,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
