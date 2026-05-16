import asyncio
import os
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://trading:trading@localhost:5432/trading_db")

# Setup logging to see what happens
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
from loguru import logger

async def test_backtest():
    from src.dashboard.routers.backtest import _run_engine_job
    
    # Let's run backtest for 1 day: 10/05/2026
    start_date = datetime(2026, 5, 10, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 11, tzinfo=timezone.utc)
    
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000) - 1
    
    logger.info(f"Test run_engine_job from {start_date} to {end_date}")
    
    try:
        res = await _run_engine_job(
            job_id="test_job",
            strategy_name="adts",
            parameters={"timeframe": "5m"},
            symbol="BTCUSDT",
            initial_balance=10000.0,
            start_ms=start_ms,
            end_ms=end_ms
        )
        logger.info("Backtest finished!")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_backtest())
