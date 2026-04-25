"""
db.py — Database Connection và Session Management
Sử dụng SQLAlchemy async với SQLite (dễ migrate sang PostgreSQL trên VPS)
"""
import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from loguru import logger

from .models import Base, BotStatus


# Đọc DATABASE_URL từ env, mặc định là SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/trading.db")

# Tạo thư mục data nếu chưa có
os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Đặt True để xem SQL queries khi debug
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Tạo bảng và khởi tạo dữ liệu mặc định"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Tạo row BotStatus mặc định nếu chưa có
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotStatus).where(BotStatus.id == 1))
        bot_status = result.scalar_one_or_none()
        if not bot_status:
            status = BotStatus(id=1, is_running=False)
            session.add(status)
            await session.commit()
    
    logger.info(f"✅ Database đã sẵn sàng: {DATABASE_URL}")


@asynccontextmanager
async def get_db():
    """Async context manager cho database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_session() -> AsyncSession:
    """Dependency cho FastAPI"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
