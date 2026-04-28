import asyncio
import os
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import select

from src.core.exchange import BinanceExchange, create_exchange_from_env
from src.core.order_manager import OrderManager
from src.core.risk_manager import RiskManager
from src.core.bot_logger import BotLogger
from src.strategies.ma_macd import MaMacdStrategy
from src.strategies.custom_sma import CustomSMAStrategy
from src.strategies.custom_macd import CustomMACDStrategy
from src.strategies.sma_trend_early_exit import SmaTrendEarlyExitStrategy
from src.strategies.sma_pullback import SmaPullbackStrategy
from src.strategies.sma_anti_sideway import SmaAntiSidewayStrategy
from src.database.db import get_db
from src.database.models import Bot, ExchangeAccount


# ── Candle close detector ─────────────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """
    Chuẩn hoá symbol về dạng ccxt (BASE/QUOTE).
    BTCUSDT   → BTC/USDT
    BTC/USDT  → BTC/USDT  (giữ nguyên)
    TRUMPUSDT → TRUMP/USDT
    """
    if "/" in symbol:
        return symbol
    # Các quote currency phổ biến, ưu tiên match dài trước
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote):
            base = symbol[: -len(quote)]
            return f"{base}/{quote}"
    return symbol  # fallback giữ nguyên


def _timeframe_to_seconds(tf: str) -> int:
    """Chuyển timeframe string sang số giây. Ví dụ: '5m' → 300."""
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        return int(tf[:-1]) * units[tf[-1]]
    except Exception:
        return 300  # fallback 5m


def _current_candle_open_ts(tf_seconds: int) -> int:
    """Trả về Unix timestamp (giây) của nến đang mở hiện tại."""
    now = int(datetime.now(timezone.utc).timestamp())
    return (now // tf_seconds) * tf_seconds


# ── BotEngine ─────────────────────────────────────────────────────────────────

class BotEngine:
    """
    Core engine quản lý 1 cấu hình Bot.
    Hỗ trợ Market Scanner: quét nhiều symbol cùng lúc.
    """

    def __init__(self, bot_id: int, account_id: int, symbols: list,
                 strategy_name: str, parameters: dict, bot_name: str = None):
        self.bot_id = bot_id
        self.account_id = account_id
        self.symbols_config = symbols or ["BTCUSDT"]
        self.strategy_name = strategy_name
        self.parameters = parameters or {}
        self.bot_name = bot_name or f"Bot#{bot_id}"

        # Parse parameters
        self.timeframe = self.parameters.get("timeframe", "5m")
        self.lookback = self.parameters.get("lookback_candles", 200)
        self.check_interval = self.parameters.get("check_interval_seconds", 60)
        self.market_type = self.parameters.get("market_type", "futures")
        self.max_open_positions = self.parameters.get("max_open_positions", 5)

        # Candle-close status report: timeframe cố định 5m
        self._report_tf_seconds = 300  # 5 phút
        self._last_reported_candle_ts: int = 0  # timestamp nến 5m đã report lần cuối

        # Components
        self.exchange: BinanceExchange = None
        self.strategy = None
        self.order_manager: OrderManager = None
        self.risk_manager: RiskManager = None
        self.log: BotLogger = None

        self.is_running = False
        self.target_symbols = []

        # Cache signal cuối cùng của mỗi symbol để dùng cho status report
        self._last_signals: dict = {}  # symbol → StrategySignal

    async def initialize(self):
        # Khởi tạo per-bot logger
        self.log = BotLogger(self.bot_id, self.bot_name)
        self.log.info(f"Đang khởi tạo BotEngine [{self.symbols_config} | {self.strategy_name}]")

        if self.account_id:
            async with get_db() as db:
                acc_result = await db.execute(
                    select(ExchangeAccount).where(ExchangeAccount.id == self.account_id)
                )
                account = acc_result.scalar_one_or_none()
                if not account:
                    raise ValueError(f"Tài khoản API ID={self.account_id} không tồn tại.")

                self.exchange = BinanceExchange(
                    api_key=account.api_key,
                    api_secret=account.api_secret,
                    mode=account.mode,
                    market_type=self.market_type,
                )
        else:
            self.exchange = create_exchange_from_env()
            self.exchange.market_type = self.market_type

        await self.exchange.connect()

        # Xác định danh sách symbols để quét
        if "ALL" in [s.upper() for s in self.symbols_config]:
            self.log.info("Chế độ ALL: Đang tải danh sách tất cả các cặp Futures...")
            markets = await self.exchange.exchange.load_markets()
            self.target_symbols = [
                sym for sym, market in markets.items()
                if market.get("linear") and market.get("active") and market["quote"] == "USDT"
            ]
            self.log.info(f"Đã tìm thấy {len(self.target_symbols)} cặp giao dịch hợp lệ.")
        elif "AUTO" in [s.upper() for s in self.symbols_config]:
            self.log.info("Chế độ AUTO: Đang tự động quét top Volume...")
            tickers = await self.exchange.exchange.fetch_tickers()
            sorted_tickers = sorted(
                [t for t in tickers.values()
                 if t.get("symbol", "").endswith("USDT") and t.get("quoteVolume")],
                key=lambda x: x.get("quoteVolume", 0),
                reverse=True,
            )
            self.target_symbols = [t["symbol"] for t in sorted_tickers[:20]]
            self.log.info(f"AUTO chọn ra: {self.target_symbols}")
        else:
            self.target_symbols = self.symbols_config

        # Init Strategy
        if self.strategy_name == "ma_macd":
            self.strategy = MaMacdStrategy(self.parameters)
        elif self.strategy_name == "custom_sma":
            self.strategy = CustomSMAStrategy(self.parameters)
        elif self.strategy_name == "custom_macd":
            self.lookback = max(
                self.lookback,
                int(self.parameters.get("signal_length", 500)) + 50,
            )
            self.strategy = CustomMACDStrategy(self.parameters)
        elif self.strategy_name == "sma_trend_early_exit":
            self.strategy = SmaTrendEarlyExitStrategy(self.parameters)
        elif self.strategy_name == "sma_pullback":
            self.strategy = SmaPullbackStrategy(self.parameters)
        elif self.strategy_name == "sma_anti_sideway":
            self.strategy = SmaAntiSidewayStrategy(self.parameters)
        else:
            raise ValueError(f"Chiến thuật không hỗ trợ: {self.strategy_name}")

        # Risk Manager
        self.risk_manager = RiskManager(self.parameters)

        # Order Manager
        self.order_manager = OrderManager(
            self.exchange, self.risk_manager, self.parameters
        )
        self.order_manager.bot_id = self.bot_id

        self.log.info(
            f"Sẵn sàng. Quét {len(self.target_symbols)} cặp mỗi {self.check_interval}s "
            f"| Timeframe: {self.timeframe} | Strategy: {self.strategy_name}"
        )

    async def start(self):
        if self.is_running:
            return

        self.is_running = True
        try:
            while self.is_running:
                await self._run_cycle()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            self.log.info("Bot bị cancel")
        except Exception as e:
            self.log.error(f"Lỗi loop bot: {e}")
        finally:
            self.is_running = False
            if self.log:
                self.log.remove()

    async def stop(self):
        self.log.info("Đang dừng bot...")
        self.is_running = False

    # ── Main cycle ────────────────────────────────────────────────────────────

    async def _run_cycle(self):
        try:
            # 1. Lấy vị thế hiện tại
            try:
                positions = await self.exchange.get_positions()
            except Exception as e:
                self.log.warning(f"Không lấy được positions, bỏ qua chu kỳ này: {e}")
                return

            open_position_symbols = [
                p["symbol"] for p in positions
                if float(p.get("contracts", p.get("size", 0))) > 0
            ]

            # 2. Quét từng symbol theo chunk
            chunk_size = 5
            for i in range(0, len(self.target_symbols), chunk_size):
                if not self.is_running:
                    break

                current_open_count = len(open_position_symbols)
                chunk = self.target_symbols[i : i + chunk_size]
                tasks = []
                for sym in chunk:
                    if (
                        current_open_count >= self.max_open_positions
                        and sym not in open_position_symbols
                    ):
                        continue
                    tasks.append(self._analyze_symbol(sym, positions, open_position_symbols))

                if tasks:
                    await asyncio.gather(*tasks)
                    await asyncio.sleep(0.2)

            # 3. Kiểm tra có nến 5m mới đóng không → gửi status report
            await self._maybe_send_candle_report(positions)

        except Exception as e:
            self.log.error(f"Lỗi _run_cycle: {e}")

    # ── Symbol analysis ───────────────────────────────────────────────────────

    async def _analyze_symbol(self, symbol: str, positions: list, open_symbols: list):
        try:
            trading_symbol = _normalize_symbol(symbol)
            ohlcv = await self.exchange.fetch_ohlcv(trading_symbol, self.timeframe, self.lookback)
            if not ohlcv or len(ohlcv) < 50:
                return

            signal = await self.strategy.analyze(
                symbol=trading_symbol,
                ohlcv_data=ohlcv,
                current_positions=positions,
            )

            # Lưu signal cuối cùng để dùng cho status report
            self._last_signals[trading_symbol] = signal

            if not signal.is_none:
                ticker = await self.exchange.fetch_ticker(trading_symbol)
                signal.price = ticker["last"]

                from src.data.indicators import ohlcv_to_dataframe, get_ma_values, get_macd_values
                df = ohlcv_to_dataframe(ohlcv)
                indicator_data = {}

                if hasattr(self.strategy, "ma_fast") and hasattr(self.strategy, "ma_slow"):
                    ma = get_ma_values(
                        df,
                        getattr(self.strategy, "ma_fast", 10),
                        getattr(self.strategy, "ma_slow", 50),
                        getattr(self.strategy, "ma_type", "ema"),
                    )
                    if ma:
                        indicator_data.update({"ma_fast": ma.fast, "ma_slow": ma.slow})

                if hasattr(self.strategy, "macd_fast") and hasattr(self.strategy, "macd_slow"):
                    macd = get_macd_values(
                        df,
                        getattr(self.strategy, "macd_fast", 12),
                        getattr(self.strategy, "macd_slow", 26),
                        getattr(self.strategy, "macd_signal", 9),
                    )
                    if macd:
                        indicator_data.update({
                            "macd": macd.macd,
                            "macd_signal": macd.signal,
                            "macd_histogram": macd.histogram,
                        })

                self.log.info(
                    f"Signal [{signal.signal.upper()}] {trading_symbol} | {signal.reason}"
                )
                await self.order_manager.process_signal(signal, indicator_data)

                if symbol not in open_symbols and (
                    "long" in signal.signal or "short" in signal.signal
                ):
                    open_symbols.append(symbol)
            else:
                # Log debug cho signal "none" — ghi vào file bot nhưng không ra stdout
                self.log.debug(
                    f"[none] {trading_symbol} | {signal.reason}"
                )

        except Exception as e:
            self.log.error(f"Lỗi quét {symbol}: {e}")

    # ── Candle status report ──────────────────────────────────────────────────

    async def _maybe_send_candle_report(self, positions: list):
        """
        Gửi Discord status report khi nến 5m vừa đóng.
        Detect bằng cách so sánh candle open timestamp hiện tại với lần report trước.
        """
        current_candle_ts = _current_candle_open_ts(self._report_tf_seconds)

        # Nến chưa đổi → chưa có nến mới đóng
        if current_candle_ts <= self._last_reported_candle_ts:
            return

        self._last_reported_candle_ts = current_candle_ts

        # Thời gian nến vừa đóng = open của nến hiện tại - 5m
        closed_candle_ts = current_candle_ts - self._report_tf_seconds
        closed_dt = datetime.fromtimestamp(closed_candle_ts, tz=timezone.utc)
        candle_time_str = closed_dt.strftime("%Y-%m-%d %H:%M UTC")

        self.log.info(f"Nến 5m đóng lúc {candle_time_str} — chuẩn bị gửi status report")

        # Xây dựng report cho từng symbol của bot này
        bot_reports = []
        pos_map = {
            p["symbol"].replace("/", ""): p.get("side")
            for p in positions
            if float(p.get("contracts", p.get("size", 0))) > 0
        }

        for sym in self.target_symbols:
            trading_symbol = _normalize_symbol(sym)
            signal = self._last_signals.get(trading_symbol)

            pos_side = pos_map.get(trading_symbol.replace("/", ""))

            if signal:
                bot_reports.append({
                    "bot_id": self.bot_id,
                    "bot_name": self.bot_name,
                    "symbol": trading_symbol,
                    "strategy_name": self.strategy_name,
                    "signal": signal.signal,
                    "reason": signal.reason,
                    "position": pos_side,
                    "metadata": signal.metadata or {},
                })
            else:
                bot_reports.append({
                    "bot_id": self.bot_id,
                    "bot_name": self.bot_name,
                    "symbol": trading_symbol,
                    "strategy_name": self.strategy_name,
                    "signal": "none",
                    "reason": "Chưa có dữ liệu phân tích",
                    "position": pos_side,
                    "metadata": {},
                })

        if not bot_reports:
            return

        try:
            from src.core.discord_notifier import send_discord_message, build_candle_status_embed
            embed = build_candle_status_embed(candle_time_str, bot_reports)
            await send_discord_message(embed=embed)
        except Exception as e:
            self.log.error(f"Lỗi gửi candle status report: {e}")
