"""
service.py — Performance Analytics Service.

Standalone module: doc du lieu tu bang Trade (status='closed') va tinh
cac chi so hieu suat giao dich. Khong phu thuoc vao bat ky app nao khac.

Metrics duoc tinh:
    - Net PnL       : Tong realized_pnl (da tru phi) tu DB
    - Win Rate      : % lenh thang / tong lenh da dong
    - Profit Factor : Tong tien thang / |Tong tien thua|
    - Max Drawdown  : Do sut giam tai khoan lon nhat (Equity Curve method)
    - Avg Duration  : Thoi gian giu lenh trung binh (gio)

Public API:
    get_bot_performance(bot_id, days)          -> BotPerformance | None
    get_strategy_performance(strategy_name, days) -> StrategyPerformance | None
    get_all_bots_performance(days)             -> list[BotPerformance]
    setup_analytics_job(scheduler)             -> None

Tuan thu ARCHITECTURE_GUIDELINES.md:
    - Chi import tu src.database va src.core
    - Khong import tu src.apps.monitoring hay bat ky app nao khac
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select

from src.core.discord_notifier import send_discord_message
from src.core.scheduler import JobConfig, SchedulerRegistry
from src.database.db import get_db
from src.database.models import Bot, Trade

# ── Constants ─────────────────────────────────────────────────────────────────

_WEEKLY_JOB_ID: str = "analytics_weekly_report"
_WEEKLY_INTERVAL_SECONDS: int = 7 * 24 * 3600  # 7 ngay
_LOCK_TTL_SECONDS: int = 300                    # 5 phut

UTC7 = timezone(timedelta(hours=7))


# ── Output Dataclasses ────────────────────────────────────────────────────────

@dataclass
class TradeMetrics:
    """Ket qua tinh toan metrics tu danh sach lenh.

    Attributes:
        total_trades: Tong so lenh da dong.
        winning_trades: So lenh thang (realized_pnl > 0).
        losing_trades: So lenh thua (realized_pnl < 0).
        win_rate_pct: Ty le thang (0.0 - 100.0).
        net_pnl: Tong PnL rong (USDT).
        gross_profit: Tong tien thang (USDT, luon duong).
        gross_loss: Tong tien thua (USDT, luon duong).
        profit_factor: gross_profit / gross_loss. None neu khong co lenh thua.
        max_drawdown: Do sut giam lon nhat (USDT, luon duong).
        avg_duration_hours: Thoi gian giu lenh trung binh (gio).
        best_trade: realized_pnl cao nhat (USDT).
        worst_trade: realized_pnl thap nhat (USDT).
    """
    total_trades:          int
    winning_trades:        int
    losing_trades:         int
    win_rate_pct:          float
    net_pnl:               float
    gross_profit:          float
    gross_loss:            float
    profit_factor:         Optional[float]
    max_drawdown:          float
    avg_duration_hours:    float
    best_trade:            float
    worst_trade:           float


@dataclass
class BotPerformance:
    """Hieu suat giao dich cua 1 bot trong khoang thoi gian.

    Attributes:
        bot_id: ID cua bot.
        bot_name: Ten hien thi cua bot.
        strategy_name: Ten chien luoc bot dang dung.
        period_days: So ngay tinh (default: 30).
        computed_at: Thoi diem tinh toan (ISO string).
        metrics: TradeMetrics chua cac chi so.
    """
    bot_id:        int
    bot_name:      str
    strategy_name: str
    period_days:   int
    computed_at:   str
    metrics:       TradeMetrics

    def to_dict(self) -> dict:
        """Chuyen sang dict JSON-serializable cho API response.

        Returns:
            Dict day du thong tin hieu suat bot.
        """
        return {
            "bot_id":        self.bot_id,
            "bot_name":      self.bot_name,
            "strategy_name": self.strategy_name,
            "period_days":   self.period_days,
            "computed_at":   self.computed_at,
            **_metrics_to_dict(self.metrics),
        }


@dataclass
class StrategyPerformance:
    """Hieu suat tong hop cua 1 strategy tren tat ca bot.

    Attributes:
        strategy_name: Ten chien luoc.
        period_days: So ngay tinh.
        bot_count: So bot dang dung strategy nay.
        computed_at: Thoi diem tinh toan (ISO string).
        metrics: TradeMetrics chua cac chi so tong hop.
    """
    strategy_name: str
    period_days:   int
    bot_count:     int
    computed_at:   str
    metrics:       TradeMetrics

    def to_dict(self) -> dict:
        """Chuyen sang dict JSON-serializable cho API response.

        Returns:
            Dict day du thong tin hieu suat strategy.
        """
        return {
            "strategy_name": self.strategy_name,
            "period_days":   self.period_days,
            "bot_count":     self.bot_count,
            "computed_at":   self.computed_at,
            **_metrics_to_dict(self.metrics),
        }


# ── Metrics Engine ────────────────────────────────────────────────────────────

def _calc_metrics(trades: list[Trade]) -> TradeMetrics:
    """Tinh toan day du cac chi so hieu suat tu danh sach lenh.

    Xu ly an toan truong hop chia cho 0 va danh sach rong.

    Args:
        trades: Danh sach Trade co status='closed', sap xep theo closed_at.

    Returns:
        TradeMetrics voi day du chi so. Tra ve metrics rong neu khong co lenh.
    """
    if not trades:
        return _empty_metrics()

    pnl_values = [float(t.realized_pnl or 0.0) for t in trades]

    total    = len(pnl_values)
    wins     = sum(1 for p in pnl_values if p > 0)
    losses   = sum(1 for p in pnl_values if p < 0)
    win_rate = round(wins / total * 100, 2) if total > 0 else 0.0

    net_pnl      = round(sum(pnl_values), 4)
    gross_profit = round(sum(p for p in pnl_values if p > 0), 4)
    gross_loss   = round(abs(sum(p for p in pnl_values if p < 0)), 4)

    profit_factor = _safe_divide(gross_profit, gross_loss)

    max_dd = _calc_max_drawdown(trades)

    avg_duration = _calc_avg_duration_hours(trades)

    best  = round(max(pnl_values), 4)
    worst = round(min(pnl_values), 4)

    return TradeMetrics(
        total_trades=total,
        winning_trades=wins,
        losing_trades=losses,
        win_rate_pct=win_rate,
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        avg_duration_hours=avg_duration,
        best_trade=best,
        worst_trade=worst,
    )


def _calc_max_drawdown(trades: list[Trade]) -> float:
    """Tinh Max Drawdown bang thuat toan Equity Curve + Peak Tracking.

    Thuat toan:
        1. Xay dung equity_curve: tong luy ke realized_pnl theo thoi gian
        2. Theo doi peak (dinh cao nhat tu dau den hien tai)
        3. drawdown[i] = peak[i] - equity_curve[i]
        4. max_drawdown = max(drawdown[i])

    Args:
        trades: Danh sach Trade co status='closed', sap xep theo closed_at.

    Returns:
        Max drawdown (USDT, luon duong). 0.0 neu khong co lenh.
    """
    if not trades:
        return 0.0

    equity   = 0.0
    peak     = 0.0
    max_dd   = 0.0

    for trade in trades:
        equity += float(trade.realized_pnl or 0.0)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown

    return round(max_dd, 4)


def _calc_avg_duration_hours(trades: list[Trade]) -> float:
    """Tinh thoi gian giu lenh trung binh (gio).

    Args:
        trades: Danh sach Trade co closed_at va created_at.

    Returns:
        Thoi gian trung binh tinh bang gio. 0.0 neu khong tinh duoc.
    """
    durations = []
    for t in trades:
        if t.closed_at and t.created_at:
            delta = t.closed_at - t.created_at
            durations.append(delta.total_seconds() / 3600)

    if not durations:
        return 0.0
    return round(sum(durations) / len(durations), 2)


def _safe_divide(numerator: float, denominator: float) -> Optional[float]:
    """Chia an toan — tra ve None neu mau so bang 0.

    Args:
        numerator: Tu so.
        denominator: Mau so.

    Returns:
        Ket qua chia (2 chu so thap phan), hoac None neu denominator = 0.
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 2)


def _empty_metrics() -> TradeMetrics:
    """Tra ve TradeMetrics rong khi khong co lenh nao.

    Returns:
        TradeMetrics voi tat ca gia tri bang 0 / None.
    """
    return TradeMetrics(
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate_pct=0.0,
        net_pnl=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        profit_factor=None,
        max_drawdown=0.0,
        avg_duration_hours=0.0,
        best_trade=0.0,
        worst_trade=0.0,
    )


def _metrics_to_dict(m: TradeMetrics) -> dict:
    """Chuyen TradeMetrics sang dict phang cho API response.

    Args:
        m: TradeMetrics instance.

    Returns:
        Dict chua tat ca chi so.
    """
    return {
        "total_trades":          m.total_trades,
        "winning_trades":        m.winning_trades,
        "losing_trades":         m.losing_trades,
        "win_rate_pct":          m.win_rate_pct,
        "net_pnl":               m.net_pnl,
        "gross_profit":          m.gross_profit,
        "gross_loss":            m.gross_loss,
        "profit_factor":         m.profit_factor,
        "max_drawdown":          m.max_drawdown,
        "avg_duration_hours":    m.avg_duration_hours,
        "best_trade":            m.best_trade,
        "worst_trade":           m.worst_trade,
    }

# ── DB Query Helpers ──────────────────────────────────────────────────────────

async def _fetch_closed_trades(
    bot_id:        Optional[int],
    strategy_name: Optional[str],
    since:         datetime,
) -> list[Trade]:
    """Query cac lenh da dong trong khoang thoi gian.

    Chi doc tu DB — khong goi exchange, khong import app khac.

    Args:
        bot_id: Loc theo bot_id. None = tat ca bot.
        strategy_name: Loc theo strategy. None = tat ca strategy.
        since: Chi lay lenh co closed_at >= since.

    Returns:
        Danh sach Trade sap xep theo closed_at tang dan.
    """
    async with get_db() as db:
        q = (
            select(Trade)
            .where(
                Trade.status == "closed",
                Trade.closed_at.isnot(None),
                Trade.closed_at >= since,
            )
            .order_by(Trade.closed_at.asc())
        )
        if bot_id is not None:
            q = q.where(Trade.bot_id == bot_id)
        if strategy_name is not None:
            q = q.where(Trade.strategy == strategy_name)

        result = await db.execute(q)
        return list(result.scalars().all())


async def _fetch_bot(bot_id: int) -> Optional[Bot]:
    """Lay thong tin Bot theo ID.

    Args:
        bot_id: ID cua bot.

    Returns:
        Bot instance hoac None neu khong tim thay.
    """
    async with get_db() as db:
        result = await db.execute(
            select(Bot).where(Bot.id == bot_id, Bot.is_deleted == False)  # noqa: E711
        )
        return result.scalar_one_or_none()


async def _fetch_all_active_bots() -> list[Bot]:
    """Lay danh sach tat ca bot chua bi xoa.

    Returns:
        Danh sach Bot sap xep theo id.
    """
    async with get_db() as db:
        result = await db.execute(
            select(Bot)
            .where(Bot.is_deleted == False)  # noqa: E711
            .order_by(Bot.id.asc())
        )
        return list(result.scalars().all())


def _since_datetime(days: int) -> datetime:
    """Tinh thoi diem bat dau cua khoang thoi gian.

    Args:
        days: So ngay nhin lai.

    Returns:
        datetime UTC naive tuong ung voi `days` ngay truoc.
    """
    return datetime.utcnow() - timedelta(days=days)


def _now_iso() -> str:
    """Tra ve thoi diem hien tai dang ISO string (UTC).

    Returns:
        ISO string UTC.
    """
    return datetime.utcnow().isoformat()


# ── Public API ────────────────────────────────────────────────────────────────

async def get_bot_performance(
    bot_id: int,
    days:   int = 30,
) -> Optional[BotPerformance]:
    """Lay chi so hieu suat cua 1 bot trong N ngay gan nhat.

    Doc tu bang Trade (status='closed') — khong goi exchange.

    Args:
        bot_id: ID cua bot can lay metrics.
        days: So ngay nhin lai (default: 30).

    Returns:
        BotPerformance hoac None neu bot khong ton tai.

    Example:
        perf = await get_bot_performance(bot_id=7, days=30)
        if perf:
            print(f"Win rate: {perf.metrics.win_rate_pct}%")
    """
    try:
        bot = await _fetch_bot(bot_id)
        if bot is None:
            logger.warning(f"[Analytics] Bot #{bot_id} khong ton tai")
            return None

        since  = _since_datetime(days)
        trades = await _fetch_closed_trades(bot_id=bot_id, strategy_name=None, since=since)
        metrics = _calc_metrics(trades)

        return BotPerformance(
            bot_id=bot.id,
            bot_name=bot.name,
            strategy_name=bot.strategy_name or "",
            period_days=days,
            computed_at=_now_iso(),
            metrics=metrics,
        )
    except Exception as exc:
        logger.error(
            f"[Analytics] Loi get_bot_performance bot_id={bot_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


async def get_strategy_performance(
    strategy_name: str,
    days:          int = 30,
) -> Optional[StrategyPerformance]:
    """Lay chi so hieu suat tong hop cua 1 strategy tren tat ca bot.

    Gop tat ca lenh cua strategy nay tu moi bot lai de tinh metrics chung.

    Args:
        strategy_name: Ten strategy (vd: "sma_macd_cross_v7").
        days: So ngay nhin lai (default: 30).

    Returns:
        StrategyPerformance hoac None neu khong co lenh nao.

    Example:
        perf = await get_strategy_performance("adts", days=7)
        if perf:
            print(f"Profit Factor: {perf.metrics.profit_factor}")
    """
    try:
        since  = _since_datetime(days)
        trades = await _fetch_closed_trades(
            bot_id=None, strategy_name=strategy_name, since=since
        )

        # Dem so bot dang dung strategy nay
        all_bots = await _fetch_all_active_bots()
        bot_count = sum(
            1 for b in all_bots if b.strategy_name == strategy_name
        )

        metrics = _calc_metrics(trades)

        return StrategyPerformance(
            strategy_name=strategy_name,
            period_days=days,
            bot_count=bot_count,
            computed_at=_now_iso(),
            metrics=metrics,
        )
    except Exception as exc:
        logger.error(
            f"[Analytics] Loi get_strategy_performance strategy={strategy_name}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


async def get_all_bots_performance(days: int = 30) -> list[BotPerformance]:
    """Lay chi so hieu suat cua tat ca bot trong N ngay gan nhat.

    Chay song song cho tung bot de giam thoi gian cho.

    Args:
        days: So ngay nhin lai (default: 30).

    Returns:
        Danh sach BotPerformance sap xep theo bot_id.
        Bot khong co lenh nao van duoc tra ve voi metrics rong.
    """
    import asyncio

    try:
        bots = await _fetch_all_active_bots()
        if not bots:
            return []

        tasks = [get_bot_performance(bot.id, days) for bot in bots]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        performances = []
        for bot, result in zip(bots, results):
            if isinstance(result, Exception):
                logger.error(
                    f"[Analytics] gather loi bot #{bot.id}: "
                    f"{type(result).__name__}: {result}"
                )
            elif result is not None:
                performances.append(result)

        return sorted(performances, key=lambda p: p.bot_id)

    except Exception as exc:
        logger.error(
            f"[Analytics] Loi get_all_bots_performance: "
            f"{type(exc).__name__}: {exc}"
        )
        return []

# ── Discord Weekly Report ─────────────────────────────────────────────────────

def _build_weekly_embed(
    performances: list[BotPerformance],
    period_days:  int,
) -> dict:
    """Tao Discord embed cho bao cao hieu suat hang tuan.

    Hien thi tung bot tren 1 field, tong ket o cuoi.

    Args:
        performances: Danh sach BotPerformance cua tat ca bot.
        period_days: So ngay bao cao.

    Returns:
        Discord embed dict.
    """
    fields = _build_bot_fields(performances)
    summary_field = _build_summary_field(performances)
    if summary_field:
        fields.append(summary_field)

    now_utc7 = datetime.now(UTC7).strftime("%Y-%m-%d %H:%M UTC+7")
    since_str = (datetime.now(UTC7) - timedelta(days=period_days)).strftime("%Y-%m-%d")
    until_str = datetime.now(UTC7).strftime("%Y-%m-%d")

    total_pnl = sum(p.metrics.net_pnl for p in performances)
    color = 0x43A047 if total_pnl >= 0 else 0xE53935

    return {
        "title": f"📊 Weekly Performance Report — {since_str} → {until_str}",
        "color": color,
        "fields": fields[:25],
        "footer": {"text": f"Trading Bot Analytics | {now_utc7}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _build_bot_fields(performances: list[BotPerformance]) -> list[dict]:
    """Tao danh sach Discord fields cho tung bot.

    Args:
        performances: Danh sach BotPerformance.

    Returns:
        List Discord field dict.
    """
    fields = []
    for p in performances:
        m = p.metrics
        if m.total_trades == 0:
            value = "_Khong co lenh nao trong ky_"
        else:
            pnl_sign = "+" if m.net_pnl >= 0 else ""
            pf_str   = f"{m.profit_factor:.2f}" if m.profit_factor is not None else "N/A"
            value = (
                f"PnL: `{pnl_sign}${m.net_pnl:.2f}` | "
                f"Win: `{m.win_rate_pct:.0f}%` ({m.winning_trades}/{m.total_trades}) | "
                f"PF: `{pf_str}` | MaxDD: `${m.max_drawdown:.2f}`"
            )
        fields.append({
            "name":   f"Bot #{p.bot_id} {p.bot_name} [{p.strategy_name}]",
            "value":  value,
            "inline": False,
        })
    return fields


def _build_summary_field(performances: list[BotPerformance]) -> Optional[dict]:
    """Tao field tong ket cho tat ca bot.

    Args:
        performances: Danh sach BotPerformance.

    Returns:
        Discord field dict hoac None neu khong co lenh.
    """
    total_trades = sum(p.metrics.total_trades for p in performances)
    if total_trades == 0:
        return None

    total_pnl  = round(sum(p.metrics.net_pnl for p in performances), 4)
    total_wins = sum(p.metrics.winning_trades for p in performances)
    win_rate   = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0.0
    pnl_sign   = "+" if total_pnl >= 0 else ""

    return {
        "name":   "📈 Tong ket",
        "value":  (
            f"**PnL: `{pnl_sign}${total_pnl:.2f}`** | "
            f"{total_trades} lenh | Win: `{win_rate:.0f}%`"
        ),
        "inline": False,
    }


async def _send_weekly_report() -> None:
    """Lay metrics va gui bao cao Discord hang tuan.

    Duoc goi boi SchedulerRegistry job moi thu Hai 08:00 UTC+7.
    Moi loi deu duoc bat va log — khong de crash scheduler.
    """
    import os
    try:
        performances = await get_all_bots_performance(days=7)
        if not performances:
            logger.info("[Analytics] Weekly report: khong co bot nao")
            return

        embed = _build_weekly_embed(performances, period_days=7)

        webhook_url = (
            os.getenv("DISCORD_REPORT_WEBHOOK_URL", "")
            or os.getenv("DISCORD_WEBHOOK_URL", "")
        )
        if not webhook_url:
            logger.warning("[Analytics] Weekly report: khong co webhook URL")
            return

        await send_discord_message(embed=embed, webhook_url=webhook_url)
        logger.info(
            f"[Analytics] Da gui weekly report cho {len(performances)} bot"
        )
    except Exception as exc:
        logger.error(
            f"[Analytics] Loi gui weekly report: "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )


# ── Job Registration ──────────────────────────────────────────────────────────

def setup_analytics_job(scheduler=None) -> None:
    """Dang ky Analytics weekly report job vao SchedulerRegistry.

    Job chay moi 7 ngay (168 gio). Lan dau chay sau khi scheduler start.
    Dung interval thay vi cron de don gian hoa — khong phu thuoc timezone.

    Args:
        scheduler: BaseScheduler instance. None = lay tu SchedulerRegistry.get().

    Example:
        # main.py
        from src.apps.analytics import setup_analytics_job
        setup_analytics_job(scheduler)
        await scheduler.start()
    """
    if scheduler is None:
        scheduler = SchedulerRegistry.get()

    scheduler.add_job(
        JobConfig(
            job_id=_WEEKLY_JOB_ID,
            func=_send_weekly_report,
            trigger="interval",
            trigger_args={"seconds": _WEEKLY_INTERVAL_SECONDS},
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            max_retries=1,
            retry_delay_seconds=30.0,
            enabled=True,
        )
    )

    logger.info(
        f"[Analytics] Job '{_WEEKLY_JOB_ID}' da dang ky "
        f"| interval=7 ngay | lock_ttl={_LOCK_TTL_SECONDS}s"
    )
