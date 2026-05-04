"""
db.py — Database Connection và Session Management
Sử dụng SQLAlchemy async với PostgreSQL (asyncpg)
"""
import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from loguru import logger

from .models import Base


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://trading:trading@localhost:5432/trading_db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
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
    logger.info(f"Database đã sẵn sàng: {DATABASE_URL.split('@')[-1]}")


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
