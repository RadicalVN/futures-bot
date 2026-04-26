import asyncio
import os
from datetime import datetime
from loguru import logger
from sqlalchemy import select

from src.core.exchange import BinanceExchange, create_exchange_from_env
from src.core.order_manager import OrderManager
from src.core.risk_manager import RiskManager
from src.strategies.ma_macd import MaMacdStrategy
from src.strategies.custom_sma import CustomSMAStrategy
from src.strategies.custom_macd import CustomMACDStrategy
from src.database.db import get_db
from src.database.models import Bot

class BotEngine:
    """
    Core engine quản lý 1 cấu hình Bot.
    Hỗ trợ Market Scanner: quét nhiều symbol cùng lúc.
    """

    def __init__(self, bot_id: int, symbols: list, strategy_name: str, parameters: dict):
        self.bot_id = bot_id
        self.symbols_config = symbols or ["BTCUSDT"]
        self.strategy_name = strategy_name
        self.parameters = parameters or {}

        # Parse parameters
        self.timeframe = self.parameters.get("timeframe", "15m")
        self.lookback = self.parameters.get("lookback_candles", 200)
        self.check_interval = self.parameters.get("check_interval_seconds", 60)
        self.market_type = self.parameters.get("market_type", "futures")
        self.max_open_positions = self.parameters.get("max_open_positions", 5)

        # Components
        self.exchange: BinanceExchange = None
        self.strategy = None
        self.order_manager: OrderManager = None
        self.risk_manager: RiskManager = None

        self.is_running = False
        self.target_symbols = []

    async def initialize(self):
        logger.info(f"Đang khởi tạo BotEngine [ID: {self.bot_id} | {self.symbols_config}]")

        self.exchange = create_exchange_from_env()
        self.exchange.market_type = self.market_type
        await self.exchange.connect()

        # Xác định danh sách symbols để quét
        if "ALL" in [s.upper() for s in self.symbols_config]:
            logger.info("Chế độ ALL: Đang tải danh sách tất cả các cặp Futures...")
            markets = await self.exchange.exchange.load_markets()
            self.target_symbols = [
                sym for sym, market in markets.items() 
                if market.get('linear') and market.get('active') and market['quote'] == 'USDT'
            ]
            logger.info(f"Đã tìm thấy {len(self.target_symbols)} cặp giao dịch hợp lệ.")
        elif "AUTO" in [s.upper() for s in self.symbols_config]:
            # Todo: Strategy quyết định, tạm thời giả lập top 10 volume
            logger.info("Chế độ AUTO: Đang tự động quét top Volume...")
            tickers = await self.exchange.exchange.fetch_tickers()
            sorted_tickers = sorted(
                [t for t in tickers.values() if t.get('symbol', '').endswith('USDT') and t.get('quoteVolume')],
                key=lambda x: x.get('quoteVolume', 0), reverse=True
            )
            self.target_symbols = [t['symbol'] for t in sorted_tickers[:20]]
            logger.info(f"AUTO chọn ra: {self.target_symbols}")
        else:
            self.target_symbols = self.symbols_config

        # Init Strategy
        if self.strategy_name == "ma_macd":
            self.strategy = MaMacdStrategy(self.parameters)
        elif self.strategy_name == "custom_sma":
            self.strategy = CustomSMAStrategy(self.parameters)
        elif self.strategy_name == "custom_macd":
            # Chỉnh lookback lớn hơn để đủ dữ liệu cho MACD signal_length (mặc định 500)
            self.lookback = max(self.lookback, int(self.parameters.get("signal_length", 500)) + 50)
            self.strategy = CustomMACDStrategy(self.parameters)
        else:
            raise ValueError(f"Chiến thuật không hỗ trợ: {self.strategy_name}")

        # Risk Manager
        self.risk_manager = RiskManager(self.parameters)

        # Order Manager
        self.order_manager = OrderManager(
            self.exchange, self.risk_manager, self.parameters
        )
        self.order_manager.bot_id = self.bot_id

        logger.info(f"BotEngine [ID: {self.bot_id}] sẵn sàng. Quét {len(self.target_symbols)} cặp mỗi {self.check_interval}s")

    async def start(self):
        if self.is_running:
            return

        self.is_running = True
        try:
            while self.is_running:
                await self._run_cycle()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info(f"Bot [ID: {self.bot_id}] bị cancel")
        except Exception as e:
            logger.exception(f"Lỗi loop Bot [ID: {self.bot_id}]: {e}")
        finally:
            self.is_running = False

    async def stop(self):
        logger.info(f"Đang dừng bot [ID: {self.bot_id}]...")
        self.is_running = False

    async def _run_cycle(self):
        try:
            # 1. Lấy vị thế hiện tại để kiểm tra giới hạn Max Open Positions
            positions = await self.exchange.get_positions()
            open_position_symbols = [p['symbol'] for p in positions if float(p['contracts']) > 0]
            
            # 2. Xử lý chia chunk (đồng thời) để chống nghẽn API
            chunk_size = 5
            for i in range(0, len(self.target_symbols), chunk_size):
                if not self.is_running:
                    break
                
                # Cập nhật lại số vị thế mở
                current_open_count = len(open_position_symbols)
                
                chunk = self.target_symbols[i:i + chunk_size]
                tasks = []
                for sym in chunk:
                    # Nếu đã đạt max position và sym này chưa có vị thế mở, bỏ qua quét
                    if current_open_count >= self.max_open_positions and sym not in open_position_symbols:
                        continue
                    
                    tasks.append(self._analyze_symbol(sym, positions, open_position_symbols))
                
                if tasks:
                    await asyncio.gather(*tasks)
                    # Chờ 1 chút giữa các chunk để tránh Limit Rate
                    await asyncio.sleep(0.2)
                    
        except Exception as e:
            logger.error(f"Lỗi _run_cycle: {e}")

    async def _analyze_symbol(self, symbol: str, positions: list, open_symbols: list):
        try:
            trading_symbol = f"{symbol}/USDT" if "/" not in symbol else symbol
            ohlcv = await self.exchange.fetch_ohlcv(trading_symbol, self.timeframe, self.lookback)
            if not ohlcv or len(ohlcv) < 50:
                return

            signal = await self.strategy.analyze(
                symbol=trading_symbol,
                ohlcv_data=ohlcv,
                current_positions=positions,
            )

            if not signal.is_none:
                ticker = await self.exchange.fetch_ticker(trading_symbol)
                signal.price = ticker["last"]

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
                
                # Cập nhật danh sách open_symbols nội bộ nếu có lệnh được phát
                if symbol not in open_symbols and ("long" in signal.signal or "short" in signal.signal):
                    open_symbols.append(symbol)

        except Exception as e:
            # logger.error(f"Lỗi quét {symbol}: {e}")
            pass
