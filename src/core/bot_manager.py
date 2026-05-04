import asyncio
from datetime import datetime, timezone, timedelta
from loguru import logger
from sqlalchemy import select
from src.database.db import get_db
from src.database.models import Bot

# Global reference để dashboard có thể lấy positions
_global_bot_manager = None

UTC7 = timezone(timedelta(hours=7))
DAILY_JOB_HOUR_UTC7   = 0   # 00:30 UTC+7
DAILY_JOB_MINUTE_UTC7 = 30
STARTUP_DELAY_MINUTES = 30  # Nếu server restart và job chưa chạy → chờ 30 phút


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
        # Chạy song song: poll bots + gửi report gộp + daily data update
        await asyncio.gather(
            self._poll_loop(),
            self._report_coordinator_loop(),
            self._daily_data_update_loop(),
        )

    async def _poll_loop(self):
        while self.is_running:
            await self._poll_bots()
            await asyncio.sleep(5)

    # ── Daily OHLCV Data Update ───────────────────────────────────────────────

    async def _daily_data_update_loop(self):
        """
        Scheduler cho job cập nhật data OHLCV hàng ngày.

        Logic:
        1. Khi khởi động: kiểm tra xem hôm nay đã chạy job chưa
           - Chưa chạy → schedule sau STARTUP_DELAY_MINUTES phút
           - Đã chạy   → schedule lúc 00:30 UTC+7 ngày mai
        2. Sau khi chạy xong → schedule lại cho ngày hôm sau
        """
        # Chờ 10s để DB và exchange sẵn sàng
        await asyncio.sleep(10)

        while self.is_running:
            try:
                wait_seconds = await self._calc_next_run_wait()
                logger.info(
                    f"[DailyDataJob] Lần chạy tiếp theo sau {wait_seconds:.0f}s "
                    f"({wait_seconds/60:.1f} phút)"
                )

                # Chờ đến giờ chạy (check mỗi 30s để có thể dừng sớm)
                waited = 0
                while waited < wait_seconds and self.is_running:
                    sleep_step = min(30, wait_seconds - waited)
                    await asyncio.sleep(sleep_step)
                    waited += sleep_step

                if not self.is_running:
                    break

                await self._run_daily_data_update()

            except Exception as e:
                logger.error(f"[DailyDataJob] Lỗi trong scheduler loop: {e}")
                await asyncio.sleep(60)

    async def _calc_next_run_wait(self) -> float:
        """
        Tính số giây cần chờ đến lần chạy tiếp theo.

        - Nếu hôm nay chưa chạy → chờ STARTUP_DELAY_MINUTES phút
        - Nếu đã chạy hôm nay   → chờ đến 00:30 UTC+7 ngày mai
        """
        from src.data.ohlcv_service import get_setting

        now_utc7 = datetime.now(UTC7)
        today_str = now_utc7.strftime("%Y-%m-%d")

        last_run = await get_setting("last_ohlcv_update_date")

        if last_run != today_str:
            # Chưa chạy hôm nay → chạy sau STARTUP_DELAY_MINUTES phút
            logger.info(
                f"[DailyDataJob] Hôm nay ({today_str}) chưa chạy "
                f"(last_run={last_run}) → schedule sau {STARTUP_DELAY_MINUTES} phút"
            )
            return STARTUP_DELAY_MINUTES * 60.0

        # Đã chạy hôm nay → chờ đến 00:30 UTC+7 ngày mai
        tomorrow_utc7 = (now_utc7 + timedelta(days=1)).replace(
            hour=DAILY_JOB_HOUR_UTC7,
            minute=DAILY_JOB_MINUTE_UTC7,
            second=0,
            microsecond=0,
        )
        wait_seconds = (tomorrow_utc7 - now_utc7).total_seconds()
        return max(wait_seconds, 60.0)

    async def _run_daily_data_update(self):
        """
        Chạy incremental update cho tất cả active datasets.
        Lưu ngày chạy vào system_settings để tránh chạy lại khi restart.
        """
        from src.data.ohlcv_service import get_active_datasets, incremental_update, set_setting
        from src.core.exchange import create_exchange_from_env

        now_utc7  = datetime.now(UTC7)
        today_str = now_utc7.strftime("%Y-%m-%d")
        logger.info(f"[DailyDataJob] Bắt đầu cập nhật data OHLCV — {today_str}")

        datasets = await get_active_datasets()
        if not datasets:
            logger.info("[DailyDataJob] Không có dataset nào cần cập nhật")
            await set_setting("last_ohlcv_update_date", today_str)
            return

        # Tạo exchange (dùng env credentials, không cần account cụ thể)
        try:
            exchange = create_exchange_from_env()
            await exchange.connect()
        except Exception as e:
            logger.error(f"[DailyDataJob] Không thể kết nối exchange: {e}")
            return

        success = 0
        failed  = 0
        try:
            for ds in datasets:
                strategy = ds["strategy_name"]
                symbol   = ds["symbol"]
                tf       = ds["timeframe"]
                try:
                    result = await incremental_update(strategy, symbol, tf, exchange)
                    inserted = result.get("total_inserted", 0)
                    logger.info(
                        f"[DailyDataJob] {strategy}/{symbol}/{tf}: "
                        f"+{inserted} nến ({result.get('status')})"
                    )
                    success += 1
                except Exception as e:
                    logger.error(f"[DailyDataJob] {strategy}/{symbol}/{tf} lỗi: {e}")
                    failed += 1
        finally:
            await exchange.close()

        logger.info(
            f"[DailyDataJob] Hoàn tất: {success} dataset OK, {failed} lỗi"
        )
        # Lưu ngày chạy dù có lỗi một số dataset (để không chạy lại ngay)
        await set_setting("last_ohlcv_update_date", today_str)

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
