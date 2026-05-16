import asyncio
import os
import sys
from sqlalchemy import text
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://trading:trading@localhost:5432/trading_db")

async def check():
    from src.database.db import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT strategy_name, symbol, timeframe, status FROM ohlcv_fetch_jobs WHERE timeframe = '1d'"))
        rows = res.fetchall()
        for r in rows:
            print(f"{r.strategy_name} | {r.symbol} | {r.timeframe} | {r.status}")

if __name__ == "__main__":
    asyncio.run(check())
