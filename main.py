"""
main.py — Bot Engine + Entry Point
Orchestrator kết nối Exchange, Strategy, OrderManager, và Dashboard
"""
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for Unicode/emoji
import io
if sys.platform == "win32" and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import yaml
from dotenv import load_dotenv
from loguru import logger

from src.core.exchange import BinanceExchange, create_exchange_from_env
from src.core.order_manager import OrderManager
from src.core.risk_manager import RiskManager
from src.strategies.ma_macd import MaMacdStrategy
from src.database.db import init_db, get_db
from src.database.models import BotStatus
from sqlalchemy import select

# Load env
load_dotenv()

# ─── Logging Setup ────────────────────────────────────────────────────
def setup_logging(config: dict):
    log_config = config.get("logging", {})
    log_level = log_config.get("level", "INFO")
    log_file = log_config.get("file", "logs/trading.log")
    max_size = log_config.get("max_size_mb", 50)
    backup = log_config.get("backup_count", 5)

    Path("logs").mkdir(exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level=log_level,
    )
    logger.add(
        log_file,
        rotation=f"{max_size} MB",
        retention=backup,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=log_level,
        encoding="utf-8",
    )


# ─── Config Loader ────────────────────────────────────────────────────
def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─── Bot Engine ───────────────────────────────────────────────────────
class BotEngine:
    """
    Core engine — điều phối toàn bộ bot:
    Exchange → MarketData → Strategy → OrderManager → DB
    """

    def __init__(self, config: dict):
        self.config = config
        self.trading_config = config.get("trading", {})
        self.strategy_config = config.get("strategy", {})
        self.risk_config = config.get("risk", {})

        self.symbols = self.trading_config.get("symbols", ["BTCUSDT"])
        self.timeframe = self.trading_config.get("timeframe", "15m")
        self.lookback = self.trading_config.get("lookback_candles", 200)
        self.check_interval = self.strategy_config.get("check_interval_seconds", 60)
        self.market_type = self.trading_config.get("market_type", "futures")

        # Components (khởi tạo khi start)
        self.exchange: BinanceExchange = None
        self.strategy: MaMacdStrategy = None
        self.order_manager: OrderManager = None
        self.risk_manager: RiskManager = None

        self.is_running = False
        self._task: asyncio.Task = None

    async def initialize(self):
        """Khởi tạo tất cả components"""
        logger.info("⚙️  Đang khởi tạo Bot Engine...")

        # Exchange
        self.exchange = create_exchange_from_env()
        self.exchange.market_type = self.market_type
        await self.exchange.connect()

        # Strategy
        self.strategy = MaMacdStrategy(self.strategy_config)

        # Risk Manager
        self.risk_manager = RiskManager(self.risk_config)

        # Order Manager
        self.order_manager = OrderManager(
            self.exchange, self.risk_manager, self.risk_config
        )

        # DB
        await init_db()
        await self._update_bot_status(is_running=False)

        logger.info(
            f"✅ Bot Engine sẵn sàng | "
            f"Strategy: {self.strategy.name} | "
            f"Symbols: {self.symbols} | "
            f"Timeframe: {self.timeframe} | "
            f"Mode: {self.exchange.mode.upper()}"
        )

    async def start(self):
        """Bắt đầu vòng lặp chính của bot"""
        if self.is_running:
            logger.warning("Bot đã đang chạy")
            return

        self.is_running = True
        await self._update_bot_status(is_running=True)
        logger.info(f"🚀 Bot bắt đầu chạy | Interval: {self.check_interval}s")

        try:
            while self.is_running:
                await self._run_cycle()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info("Bot bị cancel")
        except Exception as e:
            logger.exception(f"Lỗi nghiêm trọng trong bot loop: {e}")
        finally:
            self.is_running = False
            await self._update_bot_status(is_running=False)

    async def stop(self):
        """Dừng bot"""
        logger.info("⏹  Đang dừng bot...")
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        await self._update_bot_status(is_running=False)
        logger.info("Bot đã dừng")

    async def _run_cycle(self):
        """
        Một vòng lặp phân tích:
        1. Lấy OHLCV cho mỗi symbol
        2. Phân tích strategy → signal
        3. Thực thi signal nếu có
        """
        try:
            # Lấy vị thế hiện tại (một lần cho tất cả symbol)
            positions = await self.exchange.get_positions()
        except Exception as e:
            logger.error(f"Lỗi lấy positions: {e}")
            return

        for symbol in self.symbols:
            try:
                trading_symbol = f"{symbol}/USDT" if "/" not in symbol else symbol
                await self._analyze_symbol(trading_symbol, positions)
            except Exception as e:
                logger.error(f"Lỗi xử lý {symbol}: {e}")

    async def _analyze_symbol(self, symbol: str, positions: list):
        """Phân tích một symbol và thực thi signal nếu có"""
        # Lấy OHLCV
        ohlcv = await self.exchange.fetch_ohlcv(symbol, self.timeframe, self.lookback)
        if not ohlcv or len(ohlcv) < 50:
            logger.warning(f"Không đủ dữ liệu OHLCV cho {symbol}")
            return

        # Phân tích strategy
        signal = await self.strategy.analyze(
            symbol=symbol,
            ohlcv_data=ohlcv,
            current_positions=positions,
        )

        # Nếu có signal, thực thi
        if not signal.is_none:
            # Lấy giá hiện tại
            ticker = await self.exchange.fetch_ticker(symbol)
            signal.price = ticker["last"]

            # Tạo indicator data để lưu DB
            from src.data.indicators import ohlcv_to_dataframe, get_ma_values, get_macd_values
            df = ohlcv_to_dataframe(ohlcv)
            ma = get_ma_values(df, self.strategy.ma_fast, self.strategy.ma_slow, self.strategy.ma_type)
            macd = get_macd_values(df, self.strategy.macd_fast, self.strategy.macd_slow, self.strategy.macd_signal)

            indicator_data = {}
            if ma:
                indicator_data.update({"ma_fast": ma.fast, "ma_slow": ma.slow})
            if macd:
                indicator_data.update({
                    "macd": macd.macd,
                    "macd_signal": macd.signal,
                    "macd_histogram": macd.histogram,
                })

            await self.order_manager.process_signal(signal, indicator_data)

    async def _update_bot_status(self, is_running: bool):
        """Cập nhật trạng thái bot trong DB"""
        try:
            async with get_db() as db:
                result = await db.execute(select(BotStatus).where(BotStatus.id == 1))
                status = result.scalar_one_or_none()
                if status:
                    status.is_running = is_running
                    status.mode = os.getenv("BINANCE_MODE", "testnet")
                    if is_running:
                        status.started_at = datetime.utcnow()
        except Exception as e:
            logger.warning(f"Không update được bot status: {e}")


# ─── Main Entry Point ─────────────────────────────────────────────────
async def main():
    logger.info("=" * 60)
    logger.info("  Binance Futures Trading Bot — MA + MACD Strategy")
    logger.info("=" * 60)

    # Load config
    config_path = os.getenv("CONFIG_PATH", "config.yaml")
    config = load_config(config_path)
    setup_logging(config)

    # Khởi tạo Bot Engine
    bot = BotEngine(config)

    # Import và setup dashboard
    from src.dashboard.app import app as dashboard_app, set_bot_engine
    import uvicorn

    # Khởi tạo exchange và components
    try:
        await bot.initialize()
        logger.info("[OK] Bot Engine ready -- exchange connected")
    except ValueError as e:
        logger.warning(f"[WARN] {e}")
        logger.info("[INFO] Dashboard chay o che do demo (chua co API key)")
        logger.info("[INFO] Huong dan: copy .env.example -> .env va dien API key")
        # Vẫn init DB để dashboard hoạt động
        try:
            await init_db()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[ERR] Loi khoi tao: {e}")
        try:
            await init_db()
        except Exception:
            pass

    # Set bot engine cho dashboard (dù connected hay không)
    set_bot_engine(bot)

    # Auto-start nếu được cấu hình và exchange đã kết nối
    auto_start = os.getenv("BOT_AUTO_START", "false").lower() == "true"
    if auto_start and bot.exchange and bot.exchange.is_connected():
        logger.info("[AUTO] Khoi dong bot tu dong...")
        asyncio.create_task(bot.start())

    # Graceful shutdown
    def handle_signal(sig, frame):
        logger.info(f"Nhận tín hiệu {sig}, đang tắt...")
        asyncio.create_task(bot.stop())

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Chạy dashboard
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8000"))

    logger.info(f"[WEB] Dashboard: http://localhost:{port}")
    logger.info(f"[API] API Docs:   http://localhost:{port}/docs")

    config_uvicorn = uvicorn.Config(
        app=dashboard_app,
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config_uvicorn)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
