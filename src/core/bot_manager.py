import asyncio
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import Bot

# Global reference để dashboard có thể lấy positions
_global_bot_manager = None


async def _get_global_positions() -> list:
    """Lấy positions từ engine đầu tiên đang chạy (dùng cho dashboard)."""
    if _global_bot_manager and _global_bot_manager.engines:
        engine = next(iter(_global_bot_manager.engines.values()))
        try:
            return await engine.exchange.get_positions()
        except Exception:
            pass
    return []


def _current_5m_ts() -> int:
    now = int(datetime.now(timezone.utc).timestamp())
    return (now // 300) * 300


class BotManager:
    """Quản lý nhiều tiến trình BotEngine"""

    def __init__(self):
        self.engines = {}       # bot_id -> BotEngine
        self.is_running = False
        # Coordinator gộp report 5m
        self._pending_reports: dict = {}   # bot_id -> list[report_dict]
        self._last_sent_candle_ts: int = 0
        self._report_lock = asyncio.Lock()

    async def start(self):
        global _global_bot_manager
        _global_bot_manager = self
        logger.info("BotManager started. Đang theo dõi danh sách bot trong DB...")
        self.is_running = True
        # Chạy song song: poll bots + gửi report gộp
        await asyncio.gather(
            self._poll_loop(),
            self._report_coordinator_loop(),
        )

    async def _poll_loop(self):
        while self.is_running:
            await self._poll_bots()
            await asyncio.sleep(5)

    async def stop(self):
        logger.info("Đang dừng BotManager và tất cả các BotEngine...")
        self.is_running = False
        for bot_id, engine in self.engines.items():
            await engine.stop()
        self.engines.clear()

    # ── Report coordinator ────────────────────────────────────────────────────

    async def collect_report(self, candle_ts: int, bot_reports: list[dict]):
        """Được gọi bởi từng BotEngine khi có report 5m mới."""
        async with self._report_lock:
            if candle_ts not in self._pending_reports:
                self._pending_reports[candle_ts] = []
            self._pending_reports[candle_ts].extend(bot_reports)

    async def _report_coordinator_loop(self):
        """
        Mỗi 10 giây kiểm tra xem có nến 5m mới đóng không.
        Nếu có và đã thu thập đủ report từ các bot → gửi 1 Discord message duy nhất.
        """
        while self.is_running:
            await asyncio.sleep(10)
            try:
                await self._maybe_flush_reports()
            except Exception as e:
                logger.error(f"Lỗi report coordinator: {e}")

    async def _maybe_flush_reports(self):
        current_ts = _current_5m_ts()
        # Nến đang mở hiện tại, nến vừa đóng = current_ts - 300
        closed_ts = current_ts - 300

        async with self._report_lock:
            if closed_ts <= self._last_sent_candle_ts:
                return
            if closed_ts not in self._pending_reports:
                return

            # Chờ thêm 15s sau khi nến đóng để các bot kịp gửi report
            closed_dt = datetime.fromtimestamp(closed_ts, tz=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            seconds_since_close = (now_utc - closed_dt).total_seconds()
            if seconds_since_close < 15:
                return

            all_reports = self._pending_reports.pop(closed_ts, [])
            self._last_sent_candle_ts = closed_ts

        if not all_reports:
            return

        candle_time_str = datetime.fromtimestamp(closed_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        logger.info(f"Gửi report gộp {len(all_reports)} bot cho nến {candle_time_str}")

        try:
            from src.core.discord_notifier import (
                send_discord_message, build_candle_status_embed, DISCORD_REPORT_WEBHOOK_URL
            )
            embed = build_candle_status_embed(candle_time_str, all_reports)
            await send_discord_message(embed=embed, webhook_url=DISCORD_REPORT_WEBHOOK_URL or None)
        except Exception as e:
            logger.error(f"Lỗi gửi report gộp: {e}")

    # ── Bot polling ───────────────────────────────────────────────────────────

    async def _poll_bots(self):
        try:
            from src.core.bot_engine import BotEngine

            async with get_db() as db:
                result = await db.execute(select(Bot).where(Bot.is_deleted == False))
                bots = result.scalars().all()

                for bot in bots:
                    if bot.status == "running" and bot.id not in self.engines:
                        logger.info(f"Khởi tạo BotEngine cho bot_id={bot.id} ({bot.symbols} - {bot.strategy_name})")

                        engine = BotEngine(
                            bot_id=bot.id,
                            account_id=bot.account_id,
                            symbols=bot.symbols,
                            strategy_name=bot.strategy_name,
                            parameters=bot.parameters,
                            bot_name=bot.name,
                            bot_manager=self,   # truyền manager để engine gọi collect_report
                        )

                        try:
                            await engine.initialize()
                            self.engines[bot.id] = engine
                            asyncio.create_task(engine.start())
                        except Exception as e:
                            logger.error(f"Lỗi khởi tạo bot_id={bot.id}: {e}")
                            if engine.exchange:
                                try:
                                    await engine.exchange.close()
                                except Exception:
                                    pass
                            bot.status = "error"
                            await db.commit()

                    elif bot.status != "running" and bot.id in self.engines:
                        logger.info(f"Dừng BotEngine cho bot_id={bot.id} ({bot.symbols})")
                        engine = self.engines.pop(bot.id)
                        await engine.stop()
        except Exception as e:
            logger.error(f"Lỗi trong vòng lặp _poll_bots: {e}")
