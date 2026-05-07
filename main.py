import asyncio
import os
import signal
import sys
from pathlib import Path

import io
if sys.platform == "win32" and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import yaml
from dotenv import load_dotenv
from loguru import logger
import uvicorn

from src.database.db import init_db
from src.core.bot_manager import BotManager
from src.core.security import VaultService
from src.core.scheduler import SchedulerRegistry

load_dotenv()

def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    logger.remove()
    # Stdout: chỉ hiện log không thuộc bot cụ thể (hoặc tất cả — tuỳ chọn)
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO",
    )
    # File chung: ghi tất cả log (kể cả từ các bot), rotation 50MB
    logger.add(
        "logs/trading.log",
        rotation="50 MB",
        retention=5,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="INFO",
        encoding="utf-8",
    )

async def main():
    logger.info("=" * 60)
    logger.info("  Binance Multi-Bot Trading Platform")
    logger.info("=" * 60)

    setup_logging()

    # ── Startup validation: fail-fast nếu VAULT_ENCRYPTION_KEY thiếu/sai ──────
    try:
        VaultService.validate_key()
    except RuntimeError as e:
        logger.critical(f"[VAULT] {e}")
        logger.critical("Bot không thể khởi động khi thiếu VAULT_ENCRYPTION_KEY. Dừng lại.")
        sys.exit(1)

    try:
        await init_db()
        logger.info("[OK] Database initialized")
    except Exception as e:
        logger.error(f"[ERR] Lỗi khởi tạo DB: {e}")

    # ── Khởi tạo Background Job Scheduler ────────────────────────────────────
    # Đọc REDIS_URL từ .env, fallback về localhost nếu không có.
    # Các module khác (apps) đăng ký job của mình qua SchedulerRegistry.register()
    # TRƯỚC khi gọi scheduler.start() ở dưới.
    SchedulerRegistry.initialize()
    scheduler = SchedulerRegistry.get()

    # ── Đăng ký ExitMonitorService job ───────────────────────────────────────
    # Quét toàn bộ Trade OPEN cross-bot mỗi 30 giây.
    # Phải đăng ký TRƯỚC khi scheduler.start() để job được kích hoạt ngay.
    from src.apps.monitoring import setup_exit_monitor_job
    setup_exit_monitor_job(scheduler)

    # ── Đăng ký OHLCVCollectorService job ────────────────────────────────────
    # Thu thập dữ liệu nến OHLCV từ Binance mỗi 60 giây.
    # Quét song song tất cả (strategy, symbol, timeframe) mà Bot đang yêu cầu.
    from src.apps.data_collector import setup_data_collector_job
    setup_data_collector_job(scheduler)

    # ── Đăng ký HealthCheckService job ───────────────────────────────────────
    # Giám sát DB, Redis, Bot heartbeat và Binance API mỗi 5 phút.
    # Gửi Discord alert ngay khi phát hiện sự cố.
    from src.apps.monitoring import setup_health_check_job
    setup_health_check_job(scheduler)

    bot_manager = BotManager()
    
    # Delayed import to avoid circular dependencies
    from src.dashboard.app import app as dashboard_app, set_bot_manager
    set_bot_manager(bot_manager)

    manager_task = asyncio.create_task(bot_manager.start())

    # ── Start Scheduler (sau khi tất cả job đã được đăng ký) ─────────────────
    try:
        await scheduler.start()
        logger.info("[OK] Background Job Scheduler started")
    except Exception as e:
        logger.warning(f"[WARN] Scheduler start failed (Redis unavailable?): {e} — tiếp tục không có scheduler")

    def handle_signal(sig, frame):
        logger.info(f"Nhận tín hiệu tắt, đang dừng BotManager...")
        asyncio.create_task(bot_manager.stop())

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8000"))

    logger.info(f"[WEB] Dashboard: http://localhost:{port}")

    config_uvicorn = uvicorn.Config(
        app=dashboard_app,
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config_uvicorn)
    
    await server.serve()
    
    if not manager_task.done():
        manager_task.cancel()

    # ── Graceful shutdown Scheduler ───────────────────────────────────────────
    await scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main())
