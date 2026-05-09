"""
exit_monitor_service.py — App chuyên biệt quét và đóng lệnh đang mở.

Khác với ``src/core/exit_monitor.py`` (gắn với 1 BotEngine cụ thể),
service này hoạt động **cross-bot**: quét toàn bộ Trade OPEN trong DB,
tự khởi tạo ExchangeService cho từng tài khoản, và đóng lệnh khi
điều kiện exit của chiến lược tương ứng được thỏa mãn.

Được đăng ký vào SchedulerRegistry qua ``setup_exit_monitor_job()``,
chạy mỗi 30 giây với Redis Lock để tránh double-close.

Luồng xử lý mỗi vòng quét:
    1. Query tất cả Trade có status='filled' và closed_at IS NULL
    2. Nhóm theo account_id → tạo/cache ExchangeService
    3. Với mỗi Trade: fetch OHLCV → tính indicator → kiểm tra exit condition
    4. Nếu thỏa: close_position → tính PnL net (3 tầng) → cập nhật Trade + Bot stats
    5. Log chi tiết từng thành phần (Gross PnL, Fee, Net PnL) + Discord notification

Logic PnL (đã được Tech Lead approve):
    - Tầng 1: Dùng order["info"]["realizedPnl"] - order["info"]["commission"] nếu != 0
    - Tầng 2: Tính thủ công từ entry_price, close_price, amount, fee_rate
    - Tầng 3: Trả về 0.0 + log WARNING
    - Fee rate: Bot.parameters.get("fee_rate", 0.0005)
    - Bao gồm cả phí Entry lẫn phí Exit để ra lợi nhuận ròng chính xác
    - Cập nhật Trade.fee (tổng phí) và Trade.realized_pnl (đã trừ phí)
"""
import asyncio
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.discord_notifier import (
    DISCORD_WEBHOOK_URL,
    build_exit_embed,
    send_discord_message,
)
from src.core.exchange import BinanceExchange, create_exchange_from_account
from src.core.exit_monitor import _check_exit_condition
from src.core.scheduler import JobConfig, SchedulerRegistry
from src.strategies.factory import StrategyFactory
from src.database.db import get_db
from src.database.models import Bot, ExchangeAccount, Trade

# ── Hằng số cấu hình ─────────────────────────────────────────────────────────

_SCAN_INTERVAL_SECONDS: int = 30
"""Tần suất quét exit condition (giây)."""

_LOCK_TTL_SECONDS: int = 25
"""TTL của Redis lock — nhỏ hơn interval để tránh lock overlap khi job chạy chậm."""

_JOB_ID: str = "exit_monitor_global"
"""ID duy nhất của job trong SchedulerRegistry."""

_OHLCV_LOOKBACK: int = 60
"""Số nến OHLCV cần fetch để tính indicator (đủ cho SMA/MACD ngắn hạn)."""

_DEFAULT_TIMEFRAME: str = "5m"
"""Timeframe mặc định nếu bot không cấu hình."""

_TAKER_FEE_RATE_DEFAULT: float = 0.0005
"""Binance Futures taker fee mặc định (0.05%). Override qua Bot.parameters["fee_rate"]."""


# ── PnL Calculation ───────────────────────────────────────────────────────────

@dataclass
class PnlResult:
    """Kết quả tính toán PnL đầy đủ sau khi đóng lệnh.

    Attributes:
        gross_pnl: PnL thuần chưa trừ phí (USDT).
        fee_entry: Phí giao dịch lúc mở lệnh (USDT, luôn dương).
        fee_exit: Phí giao dịch lúc đóng lệnh (USDT, luôn dương).
        total_fee: Tổng phí = fee_entry + fee_exit (USDT).
        net_pnl: Lợi nhuận ròng = gross_pnl - total_fee (USDT).
        source: Nguồn tính toán: "exchange" | "manual" | "fallback".
        close_price: Giá đóng lệnh thực tế từ exchange.
    """
    gross_pnl:   float
    fee_entry:   float
    fee_exit:    float
    total_fee:   float
    net_pnl:     float
    source:      str
    close_price: float


def _calculate_realized_pnl(
    order:        dict,
    trade:        "Trade",
    current_price: float,
    fee_rate:     float,
) -> PnlResult:
    """Tính PnL ròng sau khi đóng lệnh — logic 3 tầng đã được Tech Lead approve.

    Công thức Futures USDT-M (không nhân leverage vào PnL vì amount đã là contract):
        LONG:  gross_pnl = (close_price - entry_price) × amount
        SHORT: gross_pnl = (entry_price - close_price) × amount
        fee_entry = entry_price × amount × fee_rate
        fee_exit  = close_price × amount × fee_rate
        net_pnl   = gross_pnl - fee_entry - fee_exit

    Tầng 1 (ưu tiên): Dùng realizedPnl từ exchange nếu != 0, trừ thêm commission.
    Tầng 2 (fallback): Tính thủ công từ entry_price, close_price, amount.
    Tầng 3 (last resort): Trả về 0.0 + log WARNING.

    Args:
        order: Order response dict từ exchange.close_position().
        trade: Trade ORM instance (cần price, amount, signal_type).
        current_price: Giá hiện tại — dùng làm fallback close_price.
        fee_rate: Tỷ lệ phí giao dịch (vd: 0.0005 cho taker 0.05%).

    Returns:
        PnlResult với đầy đủ gross_pnl, fee_entry, fee_exit, total_fee, net_pnl.
    """
    close_price = float(order.get("average") or current_price or 0.0)
    entry_price = float(trade.price or 0.0)
    amount      = float(trade.amount or 0.0)
    signal_type = trade.signal_type or "long"

    # ── Tầng 1: Dùng realizedPnl từ exchange ─────────────────────────────────
    raw_pnl        = order.get("info", {}).get("realizedPnl", None)
    raw_commission = order.get("info", {}).get("commission", None)

    try:
        exchange_pnl = float(raw_pnl) if raw_pnl not in (None, "", "0", 0) else None
    except (ValueError, TypeError):
        exchange_pnl = None

    try:
        exchange_fee_exit = abs(float(raw_commission)) if raw_commission not in (None, "", "0", 0) else None
    except (ValueError, TypeError):
        exchange_fee_exit = None

    if exchange_pnl is not None and close_price > 0 and amount > 0:
        # exchange_pnl = gross_pnl (chưa trừ phí exit theo Binance docs)
        gross_pnl = exchange_pnl
        fee_exit  = exchange_fee_exit if exchange_fee_exit is not None else close_price * amount * fee_rate
        fee_entry = entry_price * amount * fee_rate if entry_price > 0 else 0.0
        total_fee = fee_entry + fee_exit
        net_pnl   = gross_pnl - total_fee
        return PnlResult(
            gross_pnl=round(gross_pnl, 6),
            fee_entry=round(fee_entry, 6),
            fee_exit=round(fee_exit, 6),
            total_fee=round(total_fee, 6),
            net_pnl=round(net_pnl, 6),
            source="exchange",
            close_price=close_price,
        )

    # ── Tầng 2: Tính thủ công ────────────────────────────────────────────────
    if close_price > 0 and entry_price > 0 and amount > 0:
        if signal_type == "long":
            gross_pnl = (close_price - entry_price) * amount
        else:
            gross_pnl = (entry_price - close_price) * amount

        fee_entry = entry_price * amount * fee_rate
        fee_exit  = close_price * amount * fee_rate
        total_fee = fee_entry + fee_exit
        net_pnl   = gross_pnl - total_fee
        return PnlResult(
            gross_pnl=round(gross_pnl, 6),
            fee_entry=round(fee_entry, 6),
            fee_exit=round(fee_exit, 6),
            total_fee=round(total_fee, 6),
            net_pnl=round(net_pnl, 6),
            source="manual",
            close_price=close_price,
        )

    # ── Tầng 3: Fallback — không đủ dữ liệu ─────────────────────────────────
    logger.warning(
        f"[ExitMonitorService] ⚠️ Không thể tính PnL cho Trade #{trade.id} "
        f"{trade.symbol} — thiếu dữ liệu (entry={entry_price}, close={close_price}, "
        f"amount={amount}). Lưu PnL=0, cần kiểm tra thủ công."
    )
    return PnlResult(
        gross_pnl=0.0,
        fee_entry=0.0,
        fee_exit=0.0,
        total_fee=0.0,
        net_pnl=0.0,
        source="fallback",
        close_price=close_price or current_price,
    )


# ── Metadata via strategy.prepare_metadata() ─────────────────────────────────

async def _fetch_exit_meta(
    exchange:      BinanceExchange,
    symbol:        str,
    timeframe:     str,
    strategy_name: str,
    parameters:    dict,
) -> tuple[float, dict]:
    """Fetch OHLCV và delegate tính indicator sang strategy.prepare_metadata().

    ExitMonitorService không còn chứa bất kỳ indicator logic nào.
    Strategy tự biết cần tính gì — đây là nguyên tắc Zero-Core-Edit.

    Args:
        exchange: BinanceExchange instance đã connect.
        symbol: Symbol chuẩn hóa (vd: "BTC/USDT").
        timeframe: Timeframe (vd: "5m", "1h").
        strategy_name: Tên chiến lược để factory tạo instance.
        parameters: Tham số bot.

    Returns:
        Tuple (current_price, metadata_dict).
    """
    current_price = 0.0
    meta: dict = {}

    # Lấy giá ticker hiện tại
    try:
        ticker = await exchange.fetch_ticker(symbol)
        current_price = float(ticker["last"])
    except Exception as exc:
        logger.warning(f"[ExitMonitorService] fetch_ticker {symbol} lỗi: {exc}")

    # Fetch OHLCV
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, _OHLCV_LOOKBACK)
        if not ohlcv or len(ohlcv) < 10:
            return current_price, meta

        import pandas as pd
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        if not current_price:
            current_price = float(df["close"].iloc[-1])

        # Delegate tính indicator sang strategy — không hardcode gì ở đây
        try:
            strategy = StrategyFactory.create(strategy_name, parameters)
            meta = await strategy.prepare_metadata(df)
        except Exception as exc:
            logger.debug(
                f"[ExitMonitorService] prepare_metadata '{strategy_name}' lỗi: {exc}"
            )
            meta = {}

    except Exception as exc:
        logger.warning(
            f"[ExitMonitorService] _fetch_exit_meta {symbol} lỗi: {exc}"
        )

    return current_price, meta


# ── DB update helpers ─────────────────────────────────────────────────────────

async def _update_trade_closed(
    trade_id:     int,
    close_price:  float,
    realized_pnl: float,
    total_fee:    float,
) -> None:
    """Cập nhật Trade record thành 'closed' sau khi đóng lệnh thành công.

    Ghi đồng thời realized_pnl (đã trừ phí) và fee (tổng phí entry + exit).

    Args:
        trade_id: ID của Trade cần cập nhật.
        close_price: Giá đóng lệnh thực tế từ exchange.
        realized_pnl: PnL ròng đã trừ phí (USDT).
        total_fee: Tổng phí giao dịch entry + exit (USDT).
    """
    async with get_db() as db:
        result = await db.execute(select(Trade).where(Trade.id == trade_id))
        trade = result.scalar_one_or_none()
        if trade:
            trade.status       = "closed"
            trade.closed_at    = datetime.utcnow()
            trade.realized_pnl = realized_pnl
            trade.fee          = total_fee


async def _update_bot_stats(bot_id: int, net_pnl: float) -> None:
    """Cập nhật thống kê PnL và win/loss count của Bot.

    Dùng net_pnl (đã trừ phí) để phản ánh lợi nhuận thực tế.

    Args:
        bot_id: ID của Bot cần cập nhật.
        net_pnl: PnL ròng đã trừ phí (USDT). Dương = thắng, âm = thua.
    """
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.total_pnl += net_pnl
            if net_pnl > 0:
                bot.winning_trades += 1
            elif net_pnl < 0:
                bot.losing_trades += 1


# ── Exchange cache ────────────────────────────────────────────────────────────

class _ExchangeCache:
    """Cache ExchangeService instances theo account_id trong 1 vòng quét.

    Tránh tạo lại connection cho mỗi Trade thuộc cùng 1 tài khoản.
    Cache được reset sau mỗi vòng quét (không giữ qua nhiều vòng).

    Concurrency-safe: dùng asyncio.Lock per account_id để đảm bảo chỉ
    1 coroutine tạo connection cho mỗi account, ngay cả khi nhiều trade
    của cùng account chạy song song qua asyncio.gather.
    """

    def __init__(self) -> None:
        self._cache: dict[int, BinanceExchange] = {}
        # Lock per account_id — ngăn race condition khi gather chạy song song.
        # Nhiều coroutine cùng gọi get_or_create(account_id=7) sẽ serialize
        # tại đây: chỉ 1 coroutine tạo connection, các coroutine còn lại
        # chờ rồi lấy từ cache.
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, account_id: int) -> asyncio.Lock:
        """Lấy hoặc tạo Lock cho account_id.

        Không cần lock bảo vệ dict này vì asyncio là single-threaded —
        dict assignment là atomic trong CPython event loop.

        Args:
            account_id: ID của ExchangeAccount.

        Returns:
            asyncio.Lock dành riêng cho account_id này.
        """
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def get_or_create(
        self, account: ExchangeAccount, market_type: str
    ) -> Optional[BinanceExchange]:
        """Lấy exchange từ cache hoặc tạo mới nếu chưa có — concurrency-safe.

        Dùng per-account Lock để đảm bảo chỉ 1 connection được tạo
        ngay cả khi nhiều coroutine cùng request cùng account_id.

        Args:
            account: ExchangeAccount ORM instance (api_key đã encrypted).
            market_type: "futures" hoặc "spot".

        Returns:
            BinanceExchange instance đã connect, hoặc None nếu thất bại.
        """
        cache_key = account.id

        # Fast path: đã có trong cache, không cần acquire lock
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Slow path: acquire lock để tránh tạo connection trùng lặp
        async with self._get_lock(cache_key):
            # Double-check sau khi acquire lock — coroutine khác có thể đã
            # tạo xong trong lúc coroutine này đang chờ lock
            if cache_key in self._cache:
                return self._cache[cache_key]

            try:
                exchange = create_exchange_from_account(account)
                exchange.market_type = market_type
                await exchange.connect()
                self._cache[cache_key] = exchange
                logger.debug(
                    f"[ExitMonitorService] Exchange khởi tạo cho "
                    f"account_id={account.id} ({account.name}) mode={account.mode}"
                )
                return exchange
            except Exception as exc:
                logger.error(
                    f"[ExitMonitorService] Không thể khởi tạo exchange "
                    f"account_id={account.id}: {exc}"
                )
                return None

    async def close_all(self) -> None:
        """Đóng tất cả exchange connections trong cache."""
        for account_id, exchange in self._cache.items():
            try:
                await exchange.close()
            except Exception as exc:
                logger.debug(
                    f"[ExitMonitorService] Lỗi đóng exchange "
                    f"account_id={account_id}: {exc}"
                )
        self._cache.clear()
        self._locks.clear()


# ── Core exit executor ────────────────────────────────────────────────────────

async def _execute_close(
    trade:         "Trade",
    exchange:      BinanceExchange,
    current_price: float,
    exit_reason:   str,
    notify_exit:   bool,
    fee_rate:      float,
) -> None:
    """Thực thi đóng lệnh trên exchange, tính PnL net và cập nhật DB.

    Dùng trade.amount (isolated per-trade) thay vì toàn bộ position size
    để đảm bảo chế độ cách ly: mỗi lệnh chỉ đóng đúng phần của nó.

    PnL được tính theo logic 3 tầng (xem ``_calculate_realized_pnl``).
    Cập nhật đồng thời Trade.realized_pnl, Trade.fee và Bot stats.

    Args:
        trade: Trade ORM instance cần đóng.
        exchange: BinanceExchange đã connect cho tài khoản của trade.
        current_price: Giá hiện tại (fallback nếu order không trả về giá).
        exit_reason: Lý do đóng lệnh (từ _check_exit_condition).
        notify_exit: Có gửi Discord notification không.
        fee_rate: Tỷ lệ phí giao dịch từ Bot.parameters.
    """
    from src.core.bot_engine import _normalize_symbol

    if not trade.amount or trade.amount <= 0:
        logger.warning(
            f"[ExitMonitorService] Trade #{trade.id} không có amount hợp lệ "
            f"({trade.amount}) — bỏ qua"
        )
        return

    trading_symbol = _normalize_symbol(trade.symbol)
    pos_side       = trade.signal_type or "long"  # "long" | "short"

    logger.info(
        f"[ExitMonitorService] 🔒 Đóng {pos_side.upper()} {trade.symbol} "
        f"| Trade #{trade.id} | Bot #{trade.bot_id} | Reason: {exit_reason}"
    )

    try:
        order = await exchange.close_position(trading_symbol, pos_side, trade.amount)

        # ── Tính PnL net (3 tầng) ─────────────────────────────────────────────
        pnl = _calculate_realized_pnl(
            order=order,
            trade=trade,
            current_price=current_price,
            fee_rate=fee_rate,
        )

        # ── Log chi tiết từng thành phần ─────────────────────────────────────
        logger.info(
            f"[ExitMonitorService] ✅ Đóng Trade #{trade.id} {trade.symbol} "
            f"| Side: {pos_side.upper()} "
            f"| Entry: {trade.price:.4f} → Close: {pnl.close_price:.4f} "
            f"| Gross PnL: {pnl.gross_pnl:+.4f} USDT "
            f"| Fee (entry+exit): -{pnl.total_fee:.4f} USDT "
            f"| Net PnL: {pnl.net_pnl:+.4f} USDT "
            f"| Source: [{pnl.source}] "
            f"| Reason: {exit_reason}"
        )

        # ── Cập nhật DB ───────────────────────────────────────────────────────
        await _update_trade_closed(
            trade_id=trade.id,
            close_price=pnl.close_price,
            realized_pnl=pnl.net_pnl,
            total_fee=pnl.total_fee,
        )
        if trade.bot_id:
            await _update_bot_stats(trade.bot_id, pnl.net_pnl)

        if notify_exit:
            await _send_exit_notification(trade, pnl, exit_reason)

    except Exception as exc:
        logger.error(
            f"[ExitMonitorService] ❌ Lỗi đóng Trade #{trade.id} {trade.symbol}: "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )


async def _send_exit_notification(
    trade:  "Trade",
    pnl:    PnlResult,
    reason: str,
) -> None:
    """Gửi Discord notification sau khi đóng lệnh thành công.

    Hiển thị đầy đủ Gross PnL, Fee và Net PnL trong embed.

    Args:
        trade: Trade đã đóng.
        pnl: PnlResult chứa đầy đủ thông tin PnL.
        reason: Lý do đóng lệnh.
    """
    try:
        embed = build_exit_embed(
            bot_id=trade.bot_id or 0,
            signal_type=f"close_{trade.signal_type}",
            symbol=trade.symbol,
            close_price=pnl.close_price,
            pnl=pnl.net_pnl,
            reason=(
                f"[ExitMonitorService] {reason} "
                f"| Gross: {pnl.gross_pnl:+.4f} "
                f"| Fee: -{pnl.total_fee:.4f} "
                f"| Net: {pnl.net_pnl:+.4f} USDT "
                f"[{pnl.source}]"
            ),
        )
        await send_discord_message(embed=embed, webhook_url=DISCORD_WEBHOOK_URL or None)
    except Exception as exc:
        logger.debug(f"[ExitMonitorService] Lỗi gửi Discord notification: {exc}")


# ── Per-trade exit check ──────────────────────────────────────────────────────

async def _check_and_close_trade(
    trade:       "Trade",
    exchange:    BinanceExchange,
    notify_exit: bool,
    fee_rate:    float,
) -> None:
    """Kiểm tra exit condition cho 1 Trade và đóng nếu thỏa mãn.

    Args:
        trade: Trade ORM instance (status='filled', closed_at=None).
        exchange: BinanceExchange đã connect cho tài khoản của trade.
        notify_exit: Có gửi Discord notification không.
        fee_rate: Tỷ lệ phí giao dịch từ Bot.parameters (vd: 0.0005).
    """
    bot           = trade.bot
    parameters    = bot.parameters or {} if bot else {}
    strategy_name = trade.strategy or (bot.strategy_name if bot else "")
    timeframe     = parameters.get("timeframe", _DEFAULT_TIMEFRAME)

    # Fetch giá và metadata indicator mới nhất
    current_price, live_meta = await _fetch_exit_meta(
        exchange=exchange,
        symbol=trade.symbol,
        timeframe=timeframe,
        strategy_name=strategy_name,
        parameters=parameters,
    )

    if not current_price:
        logger.debug(
            f"[ExitMonitorService] Không lấy được giá cho {trade.symbol} "
            f"(Trade #{trade.id}) — bỏ qua"
        )
        return

    # Merge metadata lúc entry với metadata live
    # Quan trọng cho sma_macd_cross TH1: cần entry_deviation và ma_cross_price
    entry_meta  = dict(trade.signal_metadata or {})
    merged_meta = dict(entry_meta)
    merged_meta.update(live_meta)  # live override, nhưng giữ entry-time fields
    for key in ("entry_deviation", "ma_cross_price", "sideway_slope_threshold"):
        if key in entry_meta and key not in live_meta:
            merged_meta[key] = entry_meta[key]

    should_exit, reason = _check_exit_condition(
        strategy_name=strategy_name,
        signal_type=trade.signal_type or "long",
        current_price=current_price,
        entry_price=trade.price or 0.0,
        stop_loss=trade.stop_loss or 0.0,
        take_profit=trade.take_profit or 0.0,
        ohlcv_meta=merged_meta,
    )

    if should_exit:
        await _execute_close(
            trade=trade,
            exchange=exchange,
            current_price=current_price,
            exit_reason=reason,
            notify_exit=notify_exit,
            fee_rate=fee_rate,
        )


# ── Main service class ────────────────────────────────────────────────────────

class ExitMonitorService:
    """Service quét và đóng lệnh đang mở — chạy cross-bot, độc lập với BotEngine.

    Được đăng ký vào SchedulerRegistry qua ``setup_exit_monitor_job()``.
    Mỗi vòng quét:
        1. Query tất cả Trade OPEN từ DB (cross-bot).
        2. Cache ExchangeService theo account_id.
        3. Kiểm tra exit condition cho từng Trade.
        4. Đóng lệnh và cập nhật DB nếu thỏa mãn.

    Redis Lock được xử lý bởi BaseScheduler — không cần implement thêm ở đây.
    """

    async def run_once(self) -> None:
        """Thực thi 1 vòng quét exit condition cho toàn bộ Trade OPEN — song song.

        Dùng ``asyncio.gather`` để quét tất cả Trade đồng thời thay vì tuần tự.
        Với 50 lệnh mở, tổng thời gian ≈ thời gian của 1 lệnh chậm nhất
        thay vì tổng thời gian của 50 lệnh.

        ``_ExchangeCache`` được chia sẻ an toàn giữa các coroutine nhờ
        per-account Lock (double-checked locking pattern).

        Được gọi bởi BaseScheduler mỗi 30 giây.
        Mọi exception đều được bắt và log — không để crash scheduler.
        """
        exchange_cache = _ExchangeCache()
        try:
            open_trades = await self._load_open_trades()
            if not open_trades:
                logger.debug("[ExitMonitorService] Không có Trade OPEN nào cần quét.")
                return

            logger.info(
                f"[ExitMonitorService] Bắt đầu quét song song "
                f"{len(open_trades)} Trade OPEN..."
            )

            # Tạo coroutine cho từng trade — chạy đồng thời qua gather.
            # return_exceptions=True: 1 trade lỗi không làm hỏng các trade khác.
            tasks = [
                self._process_trade(trade, exchange_cache)
                for trade in open_trades
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log các exception bị nuốt bởi return_exceptions=True
            for trade, result in zip(open_trades, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[ExitMonitorService] ❌ gather: Trade #{trade.id} "
                        f"{trade.symbol} — {type(result).__name__}: {result}"
                    )

        except Exception as exc:
            logger.error(
                f"[ExitMonitorService] ❌ Lỗi vòng quét: "
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )
        finally:
            # Luôn đóng tất cả exchange connections sau mỗi vòng quét
            await exchange_cache.close_all()

    async def _load_open_trades(self) -> list[Trade]:
        """Query tất cả Trade đang mở từ DB.

        Dùng selectinload để eager-load Bot và ExchangeAccount trong 1 query,
        tránh N+1 query và lazy-load lỗi trong async context.

        Returns:
            Danh sách Trade có status='filled' và closed_at IS NULL.
        """
        async with get_db() as db:
            result = await db.execute(
                select(Trade)
                .options(
                    selectinload(Trade.bot).selectinload(Bot.account)
                )
                .where(
                    Trade.status == "filled",
                    Trade.closed_at == None,  # noqa: E711 — SQLAlchemy cần == None
                )
            )
            return result.scalars().all()

    async def _process_trade(
        self, trade: "Trade", exchange_cache: "_ExchangeCache"
    ) -> None:
        """Xử lý exit check cho 1 Trade.

        Lấy exchange từ cache, đọc fee_rate từ Bot.parameters,
        kiểm tra exit condition, đóng lệnh nếu cần.

        Args:
            trade: Trade ORM instance cần kiểm tra.
            exchange_cache: Cache exchange instances trong vòng quét hiện tại.
        """
        try:
            bot     = trade.bot
            account = bot.account if bot else None

            if not account:
                logger.warning(
                    f"[ExitMonitorService] Trade #{trade.id} không có ExchangeAccount "
                    f"(bot_id={trade.bot_id}) — bỏ qua"
                )
                return

            parameters  = bot.parameters or {}
            market_type = parameters.get("market_type", "futures")
            notify_exit = bool(bot.notify_exit) if bot.notify_exit is not None else True
            fee_rate    = float(parameters.get("fee_rate", _TAKER_FEE_RATE_DEFAULT))

            exchange = await exchange_cache.get_or_create(account, market_type)
            if not exchange:
                return  # Lỗi đã được log trong get_or_create

            await _check_and_close_trade(
                trade=trade,
                exchange=exchange,
                notify_exit=notify_exit,
                fee_rate=fee_rate,
            )

        except Exception as exc:
            logger.error(
                f"[ExitMonitorService] ❌ Lỗi xử lý Trade #{trade.id} "
                f"{trade.symbol}: {type(exc).__name__}: {exc}"
            )


# ── Job registration ──────────────────────────────────────────────────────────

def setup_exit_monitor_job(scheduler=None) -> None:
    """Đăng ký ExitMonitorService job vào SchedulerRegistry.

    Tạo 1 instance ExitMonitorService và đăng ký vào scheduler với:
    - Interval: 30 giây
    - Redis Lock TTL: 25 giây (< interval để tránh overlap)
    - Job ID: "exit_monitor_global"

    Nên được gọi trong ``main.py`` TRƯỚC khi ``scheduler.start()``.

    Args:
        scheduler: BaseScheduler instance. Nếu None, lấy từ SchedulerRegistry.get().

    Example:
        # main.py
        from src.apps.monitoring import setup_exit_monitor_job
        setup_exit_monitor_job()
        await SchedulerRegistry.get().start()
    """
    if scheduler is None:
        scheduler = SchedulerRegistry.get()

    service = ExitMonitorService()

    scheduler.add_job(
        JobConfig(
            job_id=_JOB_ID,
            func=service.run_once,
            trigger="interval",
            trigger_args={"seconds": _SCAN_INTERVAL_SECONDS},
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            max_retries=1,
            retry_delay_seconds=5.0,
            enabled=True,
        )
    )

    logger.info(
        f"[ExitMonitorService] Job '{_JOB_ID}' đã đăng ký "
        f"| interval={_SCAN_INTERVAL_SECONDS}s | lock_ttl={_LOCK_TTL_SECONDS}s"
    )
