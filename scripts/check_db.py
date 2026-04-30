"""Quick DB check script"""
import asyncio
import sys
sys.path.insert(0, '.')

async def check():
    from src.database.db import init_db, get_db
    from src.database.models import Trade, Bot
    from sqlalchemy import select

    await init_db()
    async with get_db() as db:
        # Check open trades
        result = await db.execute(
            select(Trade).where(Trade.status == 'filled', Trade.closed_at == None)
        )
        trades = result.scalars().all()
        print(f'=== Open trades: {len(trades)} ===')
        for t in trades:
            print(f'  Trade#{t.id} bot_id={t.bot_id} {t.signal_type} {t.symbol} amount={t.amount} price={t.price} strategy={t.strategy} created={t.created_at}')

        # Check bots status
        result2 = await db.execute(select(Bot).where(Bot.is_deleted == False))
        bots = result2.scalars().all()
        print(f'\n=== Bots ({len(bots)}) ===')
        for b in bots:
            print(f'  Bot#{b.id} [{b.status}] {b.name} | strategy={b.strategy_name} | trades={b.total_trades} | pnl={b.total_pnl:.4f}')

asyncio.run(check())
