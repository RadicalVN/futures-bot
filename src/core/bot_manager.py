import asyncio
from loguru import logger
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import Bot

class BotManager:
    """Quản lý nhiều tiến trình BotEngine"""
    def __init__(self):
        self.engines = {}  # dict lưu trữ: bot_id -> BotEngine instance
        self.is_running = False
        
    async def start(self):
        logger.info("BotManager started. Đang theo dõi danh sách bot trong DB...")
        self.is_running = True
        while self.is_running:
            await self._poll_bots()
            await asyncio.sleep(5)  # Kiểm tra DB mỗi 5 giây
            
    async def stop(self):
        logger.info("Đang dừng BotManager và tất cả các BotEngine...")
        self.is_running = False
        for bot_id, engine in self.engines.items():
            await engine.stop()
        self.engines.clear()
        
    async def _poll_bots(self):
        try:
            # Chú ý: import BotEngine ở trong hàm để tránh circular import nếu cần
            from src.core.bot_engine import BotEngine
            
            async with get_db() as db:
                result = await db.execute(select(Bot).where(Bot.is_deleted == False))
                bots = result.scalars().all()
                
                # Check for new or running bots
                for bot in bots:
                    if bot.status == "running" and bot.id not in self.engines:
                        logger.info(f"Khởi tạo BotEngine cho bot_id={bot.id} ({bot.symbols} - {bot.strategy_name})")
                        
                        engine = BotEngine(
                            bot_id=bot.id, 
                            symbols=bot.symbolss, 
                            strategy_name=bot.strategy_name, 
                            parameters=bot.parameters
                        )
                        
                        try:
                            await engine.initialize()
                            self.engines[bot.id] = engine
                            asyncio.create_task(engine.start())
                        except Exception as e:
                            logger.error(f"Lỗi khởi tạo bot_id={bot.id}: {e}")
                            bot.status = "error"
                            await db.commit()
                        
                    elif bot.status != "running" and bot.id in self.engines:
                        logger.info(f"Dừng BotEngine cho bot_id={bot.id} ({bot.symbols})")
                        engine = self.engines.pop(bot.id)
                        await engine.stop()
        except Exception as e:
            logger.error(f"Lỗi trong vòng lặp _poll_bots: {e}")
