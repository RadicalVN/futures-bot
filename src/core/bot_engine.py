import asyncio
import os
import traceback
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import select

from src.core.exchange import BinanceExchange, create_exchange_from_env
from src.core.order_manager import OrderManager
from src.core.risk_manager import RiskManager
from src.core.bot_logger import BotLogger
from src.core.exit_monitor import ExitMonitor
from src.strategies.ma_macd import MaMacdStrategy
from src.strategies.custom_sma import CustomSMAStrategy
from src.strategies.custom_macd import CustomMACDStrategy
from src.strategies.sma_trend_early_exit import SmaTrendEarlyExitStrategy
from src.strategies.sma_pullback import SmaPullbackStrategy
from src.strategies.sma_anti_sideway import SmaAntiSidewayStrategy
from src.database.db import get_db
from src.database.models import Bot, ExchangeAccount


# ── Candle close detector ─────────────────────────────────────────────────────

from src.strategies.base_strategy import StrategySignal


def _make_no_data_signal(symbol: str, reason: str) -> StrategySignal:
    """Tạo signal đặc biệt đánh dấu thiếu dữ liệu — phân biệt với signal 'none' bình thường."""
    return StrategySignal(
        signal="none",
        symbol=symbol,
        price=0,
        reason=reason,
        metadata={"no_data": True, "error": reason},
    )


def _make_error_signal(symbol: str, error: Exception, context: str = "") -> StrategySignal:
    """Tạo signal đặc biệt đánh dấu lỗi runtime — kèm traceback đầy đủ."""
    tb = traceback.format_exc()
    error_type = type(error).__name__
    short_msg = f"[{error_type}] {str(error)}"
    full_msg = f"{context}: {short_msg}" if context else short_msg
    return StrategySignal(
        signal="none",
        symbol=symbol,
        price=0,
        reason=full_msg,
        metadata={
            "no_data": True,
            "error": full_msg,
            "error_type": error_type,
            "traceback": tb[-1500:],  # Giới hạn để không quá dài
        },
    )


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
                 strategy_name: str, parameters: dict, bot_name: str = None,
                 bot_manager=None):
        self.bot_id = bot_id
        self.account_id = account_id
        self.symbols_config = symbols or ["BTCUSDT"]
        self.strategy_name = strategy_name
        self.parameters = parameters or {}
        self.bot_name = bot_name or f"Bot#{bot_id}"
        self.bot_manager = bot_manager  # BotManager coordinator

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

        # ExitMonitor — khởi tạo sau initialize()
        self.exit_monitor: ExitMonitor = None

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
        self.order_manager.strategy_name = self.strategy_name  # truyền đúng tên chiến lược

        # ExitMonitor
        self.exit_monitor = ExitMonitor(self)

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
            self.log.error(f"❌ Lỗi loop bot: {type(e).__name__}: {e}\n{traceback.format_exc()}")
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
                p["symbol"].replace("/", "").replace(":USDT", "")
                for p in positions
                if float(p.get("contracts", p.get("size", 0))) > 0
            ]

            # Tính max_open_positions động theo rủi ro vốn
            effective_max = await self._calc_effective_max_positions()

            self.log.info(
                f"▶ Quét {len(self.target_symbols)} symbol "
                f"| TF: {self.timeframe} "
                f"| Vị thế: {len(open_position_symbols)}/{effective_max}"
            )

            # 2. Quét TẤT CẢ symbol — không bỏ qua dù đã đạt max positions
            #    Việc chặn entry được xử lý trong order_manager, không phải ở đây
            chunk_size = 5
            for i in range(0, len(self.target_symbols), chunk_size):
                if not self.is_running:
                    break

                chunk = self.target_symbols[i : i + chunk_size]
                tasks = [
                    self._analyze_symbol(sym, positions, open_position_symbols, effective_max)
                    for sym in chunk
                ]
                if tasks:
                    await asyncio.gather(*tasks)
                    await asyncio.sleep(0.2)

            # 3. Chạy ExitMonitor — kiểm tra điều kiện đóng lệnh và invalidate opportunities
            if self.exit_monitor:
                await self.exit_monitor.run_once(positions)

            # 4. Kiểm tra có nến 5m mới đóng không → gửi status report
            await self._maybe_send_candle_report(positions)

        except Exception as e:
            self.log.error(
                f"❌ Lỗi _run_cycle: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )

    async def _calc_effective_max_positions(self) -> int:
        """
        Tính max_open_positions động dựa trên rủi ro vốn.
        Công thức: max_positions = floor(balance * max_portfolio_risk_pct / (position_size_pct * stop_loss_pct * leverage))
        Nếu không có max_portfolio_risk_pct → dùng max_open_positions cố định.
        """
        max_portfolio_risk_pct = self.parameters.get("max_portfolio_risk_pct", 0)
        if not max_portfolio_risk_pct:
            return self.max_open_positions  # fallback cố định

        try:
            balance = await self.exchange.get_balance()
            free = balance.get("free", 0)
            if free <= 0:
                return self.max_open_positions

            position_size_pct = self.parameters.get("position_size_pct", 0.10)
            stop_loss_pct     = self.parameters.get("stop_loss_pct", 0.02)
            leverage          = self.parameters.get("leverage", 5)

            # Rủi ro mỗi lệnh = position_size_pct * stop_loss_pct (không tính leverage vì margin isolated)
            risk_per_trade = position_size_pct * stop_loss_pct
            if risk_per_trade <= 0:
                return self.max_open_positions

            dynamic_max = int(max_portfolio_risk_pct / risk_per_trade)
            # Giới hạn tối thiểu 1, tối đa max_open_positions
            result = max(1, min(dynamic_max, self.max_open_positions))
            self.log.debug(
                f"Dynamic max positions: {result} "
                f"(balance=${free:.0f}, risk/trade={risk_per_trade*100:.1f}%, "
                f"portfolio_risk={max_portfolio_risk_pct*100:.0f}%)"
            )
            return result
        except Exception:
            return self.max_open_positions

    # ── Symbol analysis ───────────────────────────────────────────────────────

    async def _analyze_symbol(self, symbol: str, positions: list, open_symbols: list,
                               effective_max: int = None):
        trading_symbol = _normalize_symbol(symbol)
        if effective_max is None:
            effective_max = self.max_open_positions
        try:
            # ── Lấy OHLCV ────────────────────────────────────────────────────
            try:
                ohlcv = await self.exchange.fetch_ohlcv(trading_symbol, self.timeframe, self.lookback)
            except Exception as e:
                # Retry 1 lần nếu timeout
                if "Timeout" in type(e).__name__ or "timeout" in str(e).lower():
                    self.log.warning(f"⚠️ Timeout fetch OHLCV {trading_symbol}, thử lại...")
                    try:
                        import asyncio as _asyncio
                        await _asyncio.sleep(2)
                        ohlcv = await self.exchange.fetch_ohlcv(trading_symbol, self.timeframe, self.lookback)
                    except Exception as e2:
                        self.log.error(f"❌ Lỗi fetch OHLCV {trading_symbol} (retry): {type(e2).__name__}: {e2}")
                        self._last_signals[trading_symbol] = _make_error_signal(
                            trading_symbol, e2, f"fetch_ohlcv retry failed"
                        )
                        return
                else:
                    self.log.error(f"❌ Lỗi fetch OHLCV {trading_symbol}: {type(e).__name__}: {e}")
                    self._last_signals[trading_symbol] = _make_error_signal(
                        trading_symbol, e, f"fetch_ohlcv({self.timeframe}, lookback={self.lookback})"
                    )
                    return

            if not ohlcv:
                msg = f"Exchange trả về OHLCV rỗng cho {trading_symbol}"
                self.log.warning(f"⚠️ {msg}")
                self._last_signals[trading_symbol] = _make_no_data_signal(trading_symbol, msg)
                return

            if len(ohlcv) < 50:
                msg = f"Chỉ có {len(ohlcv)} nến (cần ≥50) — lookback={self.lookback}"
                self.log.warning(f"⚠️ {trading_symbol}: {msg}")
                self._last_signals[trading_symbol] = _make_no_data_signal(trading_symbol, msg)
                return

            # ── Chạy strategy ─────────────────────────────────────────────────
            try:
                signal = await self.strategy.analyze(
                    symbol=trading_symbol,
                    ohlcv_data=ohlcv,
                    current_positions=positions,
                )
            except Exception as e:
                self.log.error(
                    f"❌ Lỗi strategy.analyze {trading_symbol}: {type(e).__name__}: {e}\n"
                    f"{traceback.format_exc()}"
                )
                self._last_signals[trading_symbol] = _make_error_signal(
                    trading_symbol, e, f"strategy.analyze [{self.strategy_name}]"
                )
                return

            # ── Strategy báo không đủ dữ liệu ────────────────────────────────
            if signal.signal == "none" and "đủ dữ liệu" in signal.reason.lower():
                msg = f"{signal.reason} (lookback={self.lookback}, có={len(ohlcv)})"
                self.log.warning(f"⚠️ {trading_symbol}: {msg}")
                self._last_signals[trading_symbol] = _make_no_data_signal(trading_symbol, msg)
                return

            # Lưu signal bình thường
            self._last_signals[trading_symbol] = signal

            if not signal.is_none:
                # ── Lấy giá ticker ────────────────────────────────────────────
                try:
                    ticker = await self.exchange.fetch_ticker(trading_symbol)
                    signal.price = ticker["last"]
                except Exception as e:
                    self.log.warning(f"⚠️ Không lấy được ticker {trading_symbol}: {e} — dùng giá OHLCV")
                    signal.price = ohlcv[-1][4]  # close của nến cuối
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

                self.log.info(f"Signal [{signal.signal.upper()}] {trading_symbol} | {signal.reason}")

                # ── Lưu EntryOpportunity cho mọi signal entry ─────────────────
                if signal.is_entry:
                    await self._save_entry_opportunity(signal, effective_max, open_symbols)

                # ── Đặt lệnh — chỉ thực thi nếu chưa đạt giới hạn positions ─
                is_at_limit = (
                    signal.is_entry
                    and len(open_symbols) >= effective_max
                    and trading_symbol.replace("/", "").replace(":USDT", "") not in open_symbols
                )
                if is_at_limit:
                    self.log.info(
                        f"⚠️ [{signal.signal.upper()}] {trading_symbol} — "
                        f"Đã đạt giới hạn {effective_max} vị thế, KHÔNG đặt lệnh nhưng vẫn ghi nhận signal"
                    )
                    # Vẫn lưu signal để report Discord biết có cơ hội
                else:
                    try:
                        self.order_manager.effective_max_positions = effective_max
                        await self.order_manager.process_signal(signal, indicator_data)
                    except Exception as e:
                        self.log.error(
                            f"❌ Lỗi process_signal {trading_symbol}: {type(e).__name__}: {e}\n"
                            f"{traceback.format_exc()}"
                        )

                if symbol not in open_symbols and (
                    "long" in signal.signal or "short" in signal.signal
                ):
                    open_symbols.append(symbol)
            else:
                # Log INFO cho signal "none" với đủ thông tin để trace
                meta = signal.metadata or {}
                trend    = meta.get("trend", "?")
                prev_t   = meta.get("prev_trend", "?")
                momentum = meta.get("momentum", "?")
                slope    = meta.get("slope_pct")
                sideway  = meta.get("is_sideway")
                pullback = meta.get("was_in_pullback")

                detail_parts = [f"Trend={trend}(prev={prev_t})", f"Mom={momentum}"]
                if slope is not None:
                    detail_parts.append(f"Slope={slope:+.4f}%")
                if sideway is not None:
                    detail_parts.append(f"Sideway={'Y' if sideway else 'N'}")
                if pullback is not None:
                    detail_parts.append(f"Pullback={'Y' if pullback else 'N'}")

                self.log.info(
                    f"[WAIT] {trading_symbol} | {' | '.join(detail_parts)} | {signal.reason}"
                )

        except Exception as e:
            # Catch-all: bất kỳ lỗi nào không được bắt ở trên
            self.log.error(
                f"❌ Lỗi không xác định khi quét {trading_symbol}: {type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )
            self._last_signals[trading_symbol] = _make_error_signal(
                trading_symbol, e, "unknown error in _analyze_symbol"
            )

    async def _save_entry_opportunity(self, signal, effective_max: int, open_symbols: list):
        """Lưu EntryOpportunity vào DB cho mọi signal entry tìm được."""
        from src.database.db import get_db
        from src.database.models import EntryOpportunity
        from src.core.risk_manager import RiskManager

        sym_clean = signal.symbol.replace("/", "").replace(":USDT", "")
        executed = sym_clean not in open_symbols and len(open_symbols) < effective_max

        # Tính SL/TP từ risk manager
        sl, tp = 0.0, 0.0
        try:
            sl, tp = self.risk_manager._calculate_sl_tp(
                signal.price,
                "buy" if signal.signal == "long" else "sell"
            )
        except Exception:
            pass

        try:
            async with get_db() as db:
                opp = EntryOpportunity(
                    bot_id=self.bot_id,
                    symbol=signal.symbol,
                    signal_type=signal.signal,
                    strategy=self.strategy_name,
                    entry_price=signal.price,
                    stop_loss=sl,
                    take_profit=tp,
                    leverage=self.parameters.get("leverage", 5),
                    executed=executed,
                    is_deleted=False,
                    signal_metadata=dict(signal.metadata or {}),
                    reason=signal.reason,
                )
                db.add(opp)
            self.log.debug(
                f"💾 EntryOpportunity saved: {signal.signal.upper()} {signal.symbol} "
                f"@ {signal.price} | executed={executed}"
            )
        except Exception as e:
            self.log.error(f"❌ Lỗi lưu EntryOpportunity: {e}")

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
                enriched_meta = dict(signal.metadata or {})
                no_data = enriched_meta.get("no_data", False)
                # Đánh dấu nếu có signal nhưng đang bị giới hạn position
                sym_clean = trading_symbol.replace("/", "").replace(":USDT", "")
                at_limit = (
                    signal.signal in ("long", "short")
                    and sym_clean not in pos_map
                )
                bot_reports.append({
                    "bot_id": self.bot_id,
                    "bot_name": self.bot_name,
                    "symbol": trading_symbol,
                    "strategy_name": self.strategy_name,
                    "signal": signal.signal,
                    "reason": signal.reason,
                    "position": pos_side,
                    "metadata": enriched_meta,
                    "strategy_params": self.parameters,
                    "no_data": no_data,
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
                    "strategy_params": self.parameters,
                    "no_data": True,
                })

        if not bot_reports:
            return

        # Nếu có BotManager coordinator → gộp report, tránh rate limit Discord
        if self.bot_manager:
            await self.bot_manager.collect_report(current_candle_ts, bot_reports)
        else:
            # Fallback: tự gửi nếu không có coordinator
            try:
                from src.core.discord_notifier import send_discord_message, build_candle_status_embed, DISCORD_REPORT_WEBHOOK_URL
                embed = build_candle_status_embed(candle_time_str, bot_reports)
                await send_discord_message(embed=embed, webhook_url=DISCORD_REPORT_WEBHOOK_URL or None)
            except Exception as e:
                self.log.error(f"Lỗi gửi candle status report: {e}")
