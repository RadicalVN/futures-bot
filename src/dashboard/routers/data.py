from fastapi import APIRouter
from sqlalchemy import select, desc, func
from src.database.db import get_db
from src.database.models import BotEvent, Trade, Signal, Bot

router = APIRouter(prefix="/api", tags=["Data"])

@router.get("/events")
async def get_events(limit: int = 50):
    async with get_db() as db:
        result = await db.execute(select(BotEvent).order_by(desc(BotEvent.timestamp)).limit(limit))
        return [e.to_dict() for e in result.scalars().all()]

@router.get("/trades")
async def get_trades(limit: int = 50, bot_id: int = None, status: str = None, symbol: str = None):
    async with get_db() as db:
        q = select(Trade)
        if bot_id:
            q = q.where(Trade.bot_id == bot_id)
        if status:
            q = q.where(Trade.status == status)
        if symbol:
            q = q.where(Trade.symbol.ilike(f"%{symbol}%"))
        result = await db.execute(q.order_by(desc(Trade.created_at)).limit(limit))
        return [t.to_dict() for t in result.scalars().all()]

@router.get("/trades/open")
async def get_open_trades(bot_id: int = None):
    """Lấy các lệnh đang mở (status = filled, chưa có closed_at)"""
    async with get_db() as db:
        q = select(Trade).where(Trade.status == "filled", Trade.closed_at == None)
        if bot_id:
            q = q.where(Trade.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Trade.created_at)))
        return [t.to_dict() for t in result.scalars().all()]

@router.get("/trades/stats")
async def get_trade_stats(bot_id: int = None):
    """Thống kê PnL tổng hợp theo bot"""
    async with get_db() as db:
        # Lấy tất cả bot (không bị xóa)
        bots_result = await db.execute(select(Bot).where(Bot.is_deleted == False))
        bots = bots_result.scalars().all()

        stats = []
        for bot in bots:
            if bot_id and bot.id != bot_id:
                continue

            # Đếm trades theo status
            total_q = await db.execute(
                select(func.count(Trade.id)).where(Trade.bot_id == bot.id)
            )
            total = total_q.scalar() or 0

            closed_q = await db.execute(
                select(func.count(Trade.id)).where(
                    Trade.bot_id == bot.id,
                    Trade.status == "closed"
                )
            )
            closed = closed_q.scalar() or 0

            open_q = await db.execute(
                select(func.count(Trade.id)).where(
                    Trade.bot_id == bot.id,
                    Trade.status == "filled",
                    Trade.closed_at == None
                )
            )
            open_count = open_q.scalar() or 0

            # PnL tổng
            pnl_q = await db.execute(
                select(func.sum(Trade.realized_pnl)).where(
                    Trade.bot_id == bot.id,
                    Trade.status == "closed"
                )
            )
            total_pnl = pnl_q.scalar() or 0.0

            # Win/Loss
            win_q = await db.execute(
                select(func.count(Trade.id)).where(
                    Trade.bot_id == bot.id,
                    Trade.status == "closed",
                    Trade.realized_pnl > 0
                )
            )
            wins = win_q.scalar() or 0

            loss_q = await db.execute(
                select(func.count(Trade.id)).where(
                    Trade.bot_id == bot.id,
                    Trade.status == "closed",
                    Trade.realized_pnl < 0
                )
            )
            losses = loss_q.scalar() or 0

            win_rate = round(wins / closed * 100, 1) if closed > 0 else 0

            stats.append({
                "bot_id": bot.id,
                "bot_name": bot.name,
                "strategy_name": bot.strategy_name,
                "symbols": bot.symbols,
                "status": bot.status,
                "total_trades": total,
                "open_trades": open_count,
                "closed_trades": closed,
                "winning_trades": wins,
                "losing_trades": losses,
                "win_rate": win_rate,
                "total_pnl": round(float(total_pnl), 4),
            })

        return stats

@router.get("/signals")
async def get_signals(limit: int = 50, bot_id: int = None):
    async with get_db() as db:
        q = select(Signal)
        if bot_id:
            q = q.where(Signal.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Signal.timestamp)).limit(limit))
        return [s.to_dict() for s in result.scalars().all()]
