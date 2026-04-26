from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import Bot
from src.dashboard.schemas import BotCreate, BotStatusUpdate

router = APIRouter(prefix="/api/bots", tags=["Bots"])

@router.get("")
async def get_bots():
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.is_deleted == False))
        return [b.to_dict() for b in result.scalars().all()]

@router.post("")
async def create_bot(bot_in: BotCreate):
    async with get_db() as db:
        bot = Bot(
            name=bot_in.name,
            account_id=bot_in.account_id,
            symbols=bot_in.symbols,
            strategy_name=bot_in.strategy_name,
            parameters=bot_in.parameters,
            status="stopped"
        )
        db.add(bot)
        await db.commit()
        return {"success": True, "id": bot.id}

@router.put("/{bot_id}/status")
async def update_bot_status(bot_id: int, status_update: BotStatusUpdate):
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.is_deleted == False))
        bot = result.scalar_one_or_none()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        bot.status = status_update.status
        await db.commit()
        return {"success": True, "status": bot.status}

@router.delete("/{bot_id}")
async def delete_bot(bot_id: int):
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.is_deleted = True
            bot.status = "stopped"
            await db.commit()
        return {"success": True}
