"""
cleanup_stale_trades.py
Đánh dấu closed các trade 'filled' của bot đã stopped (không còn chạy).
Chạy 1 lần để dọn dẹp dữ liệu rác.
"""
import asyncio
import sys
sys.path.insert(0, '.')
from datetime import datetime

async def cleanup():
    from src.database.db import init_db, get_db
    from src.database.models import Trade, Bot
    from sqlalchemy import select

    await init_db()
    async with get_db() as db:
        # Lấy danh sách bot đang stopped
        result = await db.execute(
            select(Bot).where(Bot.status.in_(['stopped', 'error']), Bot.is_deleted == False)
        )
        stopped_bots = result.scalars().all()
        stopped_ids = [b.id for b in stopped_bots]
        print(f'Stopped bots: {stopped_ids}')

        # Lấy trade filled của các bot stopped
        result2 = await db.execute(
            select(Trade).where(
                Trade.status == 'filled',
                Trade.closed_at == None,
                Trade.bot_id.in_(stopped_ids)
            )
        )
        stale_trades = result2.scalars().all()
        print(f'Stale trades to cleanup: {len(stale_trades)}')

        for t in stale_trades:
            print(f'  Marking closed: Trade#{t.id} bot={t.bot_id} {t.signal_type} {t.symbol} amount={t.amount}')
            t.status = 'closed'
            t.closed_at = datetime.utcnow()
            t.realized_pnl = 0.0  # không biết PnL thực tế

        print(f'\nDone. Marked {len(stale_trades)} trades as closed.')

asyncio.run(cleanup())
