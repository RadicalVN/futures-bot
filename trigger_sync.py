import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://trading:trading@localhost:5432/trading_db")
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def trigger_sync():
    from src.data.ohlcv_service import OHLCVService
    
    svc = OHLCVService()
    await svc.trigger_update_all()
    print("Sync triggered. Waiting for jobs to complete...")
    
    # Wait for the background worker to process jobs
    # In this app, OHLCVService might process it automatically, or we might need to run the worker
    from src.database.db import AsyncSessionLocal
    from src.database.models import OHLCVFetchJob
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as db:
        while True:
            res = await db.execute(select(OHLCVFetchJob).where(OHLCVFetchJob.status.in_(["pending", "running"])))
            jobs = res.scalars().all()
            if not jobs:
                print("All fetch jobs completed.")
                break
            print(f"Waiting for {len(jobs)} jobs to complete...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(trigger_sync())
