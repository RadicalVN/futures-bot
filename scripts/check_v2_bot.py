import asyncio, sys
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot
    from sqlalchemy import select
    await init_db()
    async with get_db() as db:
        r = await db.execute(select(Bot).where(Bot.is_deleted == False).order_by(Bot.id.desc()).limit(5))
        bots = r.scalars().all()
        for b in bots:
            print(f"ID={b.id} name={b.name} strategy={b.strategy_name} params={b.parameters}")

asyncio.run(main())
