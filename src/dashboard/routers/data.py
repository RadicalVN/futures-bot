from fastapi import APIRouter
from sqlalchemy import select, desc
from src.database.db import get_db
from src.database.models import BotEvent, Trade, Signal

router = APIRouter(prefix="/api", tags=["Data"])

@router.get("/events")
async def get_events(limit: int = 50):
    async with get_db() as db:
        result = await db.execute(select(BotEvent).order_by(desc(BotEvent.timestamp)).limit(limit))
        return [e.to_dict() for e in result.scalars().all()]

@router.get("/trades")
async def get_trades(limit: int = 50, bot_id: int = None):
    async with get_db() as db:
        q = select(Trade)
        if bot_id:
            q = q.where(Trade.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Trade.created_at)).limit(limit))
        return [t.to_dict() for t in result.scalars().all()]

@router.get("/signals")
async def get_signals(limit: int = 50, bot_id: int = None):
    async with get_db() as db:
        q = select(Signal)
        if bot_id:
            q = q.where(Signal.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Signal.timestamp)).limit(limit))
        return [s.to_dict() for s in result.scalars().all()]
