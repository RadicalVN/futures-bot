from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import Bot
from src.dashboard.schemas import BotCreate, BotStatusUpdate, BotSettingsUpdate

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
            status="stopped",
            # Defaults: tất cả bật khi tạo mới
            allow_new_entry=True,
            notify_entry=True,
            allow_exit_scan=True,
            notify_exit=True,
        )
        db.add(bot)
        await db.commit()
        return {"success": True, "id": bot.id}


@router.put("/{bot_id}/status")
async def update_bot_status(bot_id: int, status_update: BotStatusUpdate):
    """
    Cập nhật trạng thái bot.
    Khi chuyển sang stopped: tự động tắt allow_new_entry để không vào lệnh mới.
    Khi chuyển sang running: tự động bật lại allow_new_entry.
    """
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.is_deleted == False))
        bot = result.scalar_one_or_none()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        new_status = status_update.status
        bot.status = new_status

        # Enforce: stopped → không vào lệnh mới
        if new_status == "stopped":
            bot.allow_new_entry = False
        elif new_status == "running":
            # Khi start lại, bật allow_new_entry (user có thể tắt lại thủ công sau)
            bot.allow_new_entry = True

        await db.commit()
        return {
            "success": True,
            "status": bot.status,
            "allow_new_entry": bot.allow_new_entry,
        }


@router.put("/{bot_id}/settings")
async def update_bot_settings(bot_id: int, settings: BotSettingsUpdate):
    """
    Cập nhật job behavior settings của bot.
    Chỉ cập nhật các field được truyền vào (partial update).
    
    - allow_new_entry: Cho phép vào lệnh mới
    - notify_entry: Gửi noti Discord khi tìm thấy entry (kể cả khi bị chặn)
    - allow_exit_scan: Quét đóng lệnh đang mở và invalidate entry opportunities
    - notify_exit: Gửi noti Discord khi đóng lệnh / invalidate entry
    """
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.is_deleted == False))
        bot = result.scalar_one_or_none()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        if settings.allow_new_entry is not None:
            bot.allow_new_entry = settings.allow_new_entry
        if settings.notify_entry is not None:
            bot.notify_entry = settings.notify_entry
        if settings.allow_exit_scan is not None:
            bot.allow_exit_scan = settings.allow_exit_scan
        if settings.notify_exit is not None:
            bot.notify_exit = settings.notify_exit

        await db.commit()
        return {
            "success": True,
            "bot_id": bot_id,
            "allow_new_entry": bot.allow_new_entry,
            "notify_entry": bot.notify_entry,
            "allow_exit_scan": bot.allow_exit_scan,
            "notify_exit": bot.notify_exit,
        }


@router.delete("/{bot_id}")
async def delete_bot(bot_id: int):
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.is_deleted = True
            bot.status = "stopped"
            bot.allow_new_entry = False
            await db.commit()
        return {"success": True}
