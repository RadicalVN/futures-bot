"""
models.py — SQLAlchemy ORM Models
Cấu trúc Database chuyên nghiệp cho Nền tảng Bot Trading
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, JSON,
    ForeignKey, Text, BigInteger, UniqueConstraint, Index,
)
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

    # ── Job behavior settings ─────────────────────────────────────────────────
    # Khi bot stopped: allow_new_entry tự động = False
    # Các flag này cho phép tuỳ chỉnh hành vi khi bot đang running
    allow_new_entry  = Column(Boolean, default=True)   # Cho phép vào lệnh mới
    notify_entry     = Column(Boolean, default=True)   # Gửi noti khi tìm thấy entry
    allow_exit_scan  = Column(Boolean, default=True)   # Quét đóng lệnh / invalidate entry
    notify_exit      = Column(Boolean, default=True)   # Gửi noti khi đóng lệnh / entry

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
            "allow_new_entry": self.allow_new_entry if self.allow_new_entry is not None else True,
            "notify_entry": self.notify_entry if self.notify_entry is not None else True,
            "allow_exit_scan": self.allow_exit_scan if self.allow_exit_scan is not None else True,
            "notify_exit": self.notify_exit if self.notify_exit is not None else True,
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
    stop_loss = Column(Float)
    take_profit = Column(Float)
    signal_metadata = Column(JSON, default={})  # metadata từ strategy lúc entry (entry_deviation, ma_cross_price, ...)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)
    
    def to_dict(self):
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "bot_name": self.bot.name if self.bot else None,
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


class EntryOpportunity(Base):
    """
    Lưu tất cả signal entry tìm được, kể cả khi không vào lệnh do giới hạn position.
    Job ExitMonitor sẽ quét bảng này để invalidate khi điều kiện exit xuất hiện.
    """
    __tablename__ = "entry_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)

    bot_id       = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=True)
    bot          = relationship("Bot")

    symbol       = Column(String(20), nullable=False, index=True)
    signal_type  = Column(String(10), nullable=False)   # "long" | "short"
    strategy     = Column(String(50))
    entry_price  = Column(Float)                        # Giá tại thời điểm tìm thấy
    stop_loss    = Column(Float)
    take_profit  = Column(Float)
    leverage     = Column(Integer, default=1)

    # Trạng thái
    executed     = Column(Boolean, default=False)       # True = đã vào lệnh thực tế
    is_deleted   = Column(Boolean, default=False)       # True = đã invalidate (exit condition met)
    delete_reason = Column(String(200))                 # Lý do invalidate

    # Metadata từ strategy
    signal_metadata = Column("metadata", JSON, default={})  # slope, momentum, trend, ...
    reason       = Column(String(500))                  # Lý do signal từ strategy

    created_at   = Column(DateTime, default=datetime.utcnow)
    invalidated_at = Column(DateTime)

    def to_dict(self):
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "bot_name": self.bot.name if self.bot else None,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "strategy": self.strategy,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "leverage": self.leverage,
            "executed": self.executed,
            "is_deleted": self.is_deleted,
            "delete_reason": self.delete_reason,
            "metadata": self.signal_metadata,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
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


# ══════════════════════════════════════════════════════════════════════════════
# OHLCV Market Data Cache
# ══════════════════════════════════════════════════════════════════════════════

class OHLCVCandle(Base):
    """
    Cache dữ liệu nến OHLCV theo từng chiến lược.
    Mỗi chiến lược có tập data riêng (strategy_name + symbol + timeframe).
    Primary key composite để đảm bảo không duplicate.
    """
    __tablename__ = "ohlcv_candles"

    # Composite PK: (strategy_name, symbol, timeframe, timestamp_ms)
    strategy_name = Column(String(50),  nullable=False, primary_key=True)
    symbol        = Column(String(20),  nullable=False, primary_key=True)
    timeframe     = Column(String(10),  nullable=False, primary_key=True)
    timestamp_ms  = Column(BigInteger,  nullable=False, primary_key=True)

    open   = Column(Float, nullable=False)
    high   = Column(Float, nullable=False)
    low    = Column(Float, nullable=False)
    close  = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        # Index để query range nhanh
        Index(
            "ix_ohlcv_strategy_symbol_tf_ts",
            "strategy_name", "symbol", "timeframe", "timestamp_ms",
        ),
    )

    def to_list(self):
        """Trả về dạng [ts_ms, open, high, low, close, volume] — tương thích với ccxt"""
        return [self.timestamp_ms, self.open, self.high, self.low, self.close, self.volume]


class OHLCVFetchJob(Base):
    """
    Theo dõi tiến trình fetch data theo từng chunk thời gian.
    Mỗi job được chia thành nhiều chunk (mỗi chunk ~30 ngày).
    Nếu fail ở chunk nào → đánh dấu để retry, không cần kéo lại từ đầu.
    """
    __tablename__ = "ohlcv_fetch_jobs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    job_key       = Column(String(200), nullable=False, index=True)
    # job_key = "{strategy_name}:{symbol}:{timeframe}:{job_type}"
    # job_type: "full_refresh" | "incremental"

    strategy_name = Column(String(50),  nullable=False)
    symbol        = Column(String(20),  nullable=False)
    timeframe     = Column(String(10),  nullable=False)
    job_type      = Column(String(20),  nullable=False)  # full_refresh | incremental

    # Trạng thái tổng thể
    status        = Column(String(20),  default="pending")
    # pending | running | done | partial_done | failed

    # Tổng số chunk và tiến độ
    total_chunks  = Column(Integer, default=0)
    done_chunks   = Column(Integer, default=0)
    failed_chunks = Column(Integer, default=0)

    # Thống kê
    total_candles_inserted = Column(Integer, default=0)
    error_message          = Column(Text,    nullable=True)

    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    # Quan hệ với các chunk
    chunks = relationship(
        "OHLCVFetchChunk", back_populates="job",
        cascade="all, delete-orphan",
        order_by="OHLCVFetchChunk.chunk_index",
    )

    def to_dict(self):
        progress = (
            round(self.done_chunks / self.total_chunks * 100, 1)
            if self.total_chunks > 0 else 0
        )
        return {
            "id":             self.id,
            "job_key":        self.job_key,
            "strategy_name":  self.strategy_name,
            "symbol":         self.symbol,
            "timeframe":      self.timeframe,
            "job_type":       self.job_type,
            "status":         self.status,
            "total_chunks":   self.total_chunks,
            "done_chunks":    self.done_chunks,
            "failed_chunks":  self.failed_chunks,
            "progress_pct":   progress,
            "total_candles_inserted": self.total_candles_inserted,
            "error_message":  self.error_message,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
            "updated_at":     self.updated_at.isoformat() if self.updated_at else None,
            "finished_at":    self.finished_at.isoformat() if self.finished_at else None,
        }


class OHLCVFetchChunk(Base):
    """
    Một chunk thời gian trong job fetch.
    Mỗi chunk = 30 ngày dữ liệu.
    Trạng thái độc lập → fail 1 chunk không ảnh hưởng chunk khác.
    """
    __tablename__ = "ohlcv_fetch_chunks"

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    job_id      = Column(Integer,    ForeignKey("ohlcv_fetch_jobs.id", ondelete="CASCADE"), nullable=False)
    job         = relationship("OHLCVFetchJob", back_populates="chunks")

    chunk_index = Column(Integer,    nullable=False)   # 0-based index trong job
    start_ms    = Column(BigInteger, nullable=False)   # Timestamp bắt đầu chunk (ms)
    end_ms      = Column(BigInteger, nullable=False)   # Timestamp kết thúc chunk (ms)

    status      = Column(String(20), default="pending")
    # pending | running | done | failed | retrying

    candles_inserted = Column(Integer, default=0)
    retry_count      = Column(Integer, default=0)
    error_message    = Column(Text,    nullable=True)

    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_ohlcv_chunk_job_idx", "job_id", "chunk_index"),
        UniqueConstraint("job_id", "chunk_index", name="uq_ohlcv_chunk_job_idx"),
    )

    def to_dict(self):
        return {
            "id":               self.id,
            "job_id":           self.job_id,
            "chunk_index":      self.chunk_index,
            "start_ms":         self.start_ms,
            "end_ms":           self.end_ms,
            "status":           self.status,
            "candles_inserted": self.candles_inserted,
            "retry_count":      self.retry_count,
            "error_message":    self.error_message,
        }


class SystemSetting(Base):
    """
    Key-value store cho cài đặt hệ thống.
    Dùng để lưu trạng thái scheduler (last_ohlcv_update_date, ...).
    """
    __tablename__ = "system_settings"

    key        = Column(String(100), primary_key=True)
    value      = Column(Text,        nullable=True)
    updated_at = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def make(cls, key: str, value: str) -> "SystemSetting":
        return cls(key=key, value=value)
