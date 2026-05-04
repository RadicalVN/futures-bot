"""Cap nhat bb_length=200 cho tat ca bot dung sma_macd_cross (V1 va V4)"""
import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot
    from sqlalchemy import select
    await init_db()
    async with get_db() as db:
        result = await db.execute(
            select(Bot).where(
                Bot.strategy_name.in_(["sma_macd_cross", "sma_macd_cross_v4"]),
                Bot.is_deleted == False
            )
        )
        bots = result.scalars().all()
        for b in bots:
            params = dict(b.parameters or {})
            old_bb = params.get("bb_length", "N/A")
            params["bb_length"] = 200
            b.parameters = params
            sys.stdout.write(f"Bot#{b.id} {b.name} ({b.strategy_name}): bb_length {old_bb} -> 200\n")
    sys.stdout.write("Done.\n")

asyncio.run(main())
