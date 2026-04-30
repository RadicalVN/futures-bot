"""Check Bot#7 and Bot#8 trades in detail"""
import asyncio
import sys
sys.path.insert(0, '.')

async def check():
    from src.database.db import init_db, get_db
    from src.database.models import Trade
    from sqlalchemy import select

    await init_db()
    async with get_db() as db:
        # All trades for bot 7 and 8
        result = await db.execute(
            select(Trade).where(Trade.bot_id.in_([7, 8])).order_by(Trade.created_at.desc())
        )
        trades = result.scalars().all()
        print(f'=== Bot#7 & Bot#8 trades: {len(trades)} ===')
        for t in trades:
            print(f'  Trade#{t.id} bot={t.bot_id} {t.signal_type} {t.symbol} '
                  f'amount={t.amount} price={t.price} status={t.status} '
                  f'closed={t.closed_at} pnl={t.realized_pnl}')

asyncio.run(check())
