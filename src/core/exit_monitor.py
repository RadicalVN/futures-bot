"""
exit_monitor.py — Job quét định kỳ để:
1. Đóng các lệnh đang mở (Trade.status=filled) khi điều kiện exit của chiến lược thỏa
2. Invalidate các EntryOpportunity chưa thực thi khi điều kiện exit xuất hiện
   (đánh dấu is_deleted=True để biết cơ hội đó đã qua)

Chạy mỗi check_interval giây, song song với _run_cycle của BotEngine.
"""
import traceback
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.db import get_db
from src.database.models import Trade, EntryOpportunity, Bot
from src.core.discord_notifier import send_discord_message, build_exit_embed, DISCORD_WEBHOOK_URL


# ── Exit condition checkers ───────────────────────────────────────────────────

def _check_exit_condition(
    strategy_name: str,
    signal_type: str,   # "long" | "short"
    current_price: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    ohlcv_meta: dict,   # metadata từ strategy (trend, momentum, slope, ...)
) -> tuple[bool, str]:
    """
    Kiểm tra điều kiện exit dựa trên chiến lược và giá hiện tại.
    Returns: (should_exit: bool, reason: str)
    """
    # ── SL / TP cứng (áp dụng cho tất cả chiến lược) ─────────────────────────
    if signal_type == "long":
        if stop_loss and current_price <= stop_loss:
            return True, f"🛑 Cắt lỗ (SL): Giá {current_price:.4f} ≤ SL {stop_loss:.4f}"
        if take_profit and current_price >= take_profit:
            return True, f"🎯 Chốt lời (TP): Giá {current_price:.4f} ≥ TP {take_profit:.4f}"
    elif signal_type == "short":
        if stop_loss and current_price >= stop_loss:
            return True, f"🛑 Cắt lỗ (SL): Giá {current_price:.4f} ≥ SL {stop_loss:.4f}"
        if take_profit and current_price <= take_profit:
            return True, f"🎯 Chốt lời (TP): Giá {current_price:.4f} ≤ TP {take_profit:.4f}"

    # ── Exit theo chiến lược (dùng metadata từ lần analyze gần nhất) ─────────
    trend    = ohlcv_meta.get("trend")
    momentum = ohlcv_meta.get("momentum", "")
    slope    = ohlcv_meta.get("slope_pct", 0.0)
    is_sideway = ohlcv_meta.get("is_sideway", False)

    WEAKENING = {"orange", "yellow", "green"}
    STRONG_BEAR = {"red"}
    STRONG_BULL = {"blue"}

    if strategy_name == "sma_trend_early_exit":
        if signal_type == "long":
            if momentum in WEAKENING:
                return True, f"📉 Thoát sớm: Momentum suy yếu ({momentum})"
            if trend == -1:
                return True, f"📉 Trend đảo Giảm"
        elif signal_type == "short":
            if momentum in WEAKENING:
                return True, f"📈 Thoát sớm: Momentum suy yếu ({momentum})"
            if trend == 1:
                return True, f"📈 Trend đảo Tăng"

    elif strategy_name == "sma_pullback":
        if signal_type == "long":
            if trend == -1 or momentum in STRONG_BEAR:
                return True, f"📉 Trend đảo hoặc Momentum giảm mạnh ({momentum})"
        elif signal_type == "short":
            if trend == 1 or momentum in STRONG_BULL:
                return True, f"📈 Trend đảo hoặc Momentum tăng mạnh ({momentum})"

    elif strategy_name == "sma_anti_sideway":
        sideway_thr = ohlcv_meta.get("sideway_slope_threshold", 0.01)
        if is_sideway or abs(slope) < sideway_thr:
            return True, f"😴 Thị trường về Sideway (|Slope|={abs(slope):.4f}%)"
        if signal_type == "long" and trend == -1:
            return True, f"📉 Trend đảo Giảm"
        if signal_type == "short" and trend == 1:
            return True, f"📈 Trend đảo Tăng"

    return False, ""


# ── ExitMonitor ───────────────────────────────────────────────────────────────

class ExitMonitor:
    """
    Chạy song song với BotEngine.
    Mỗi chu kỳ:
    1. Lấy giá và metadata mới nhất từ exchange + strategy
    2. Kiểm tra điều kiện exit cho Trade đang mở
    3. Kiểm tra điều kiện exit cho EntryOpportunity chưa thực thi
    4. Gửi noti Discord khi có action
    """

    def __init__(self, bot_engine):
        """bot_engine: BotEngine instance để dùng exchange, strategy, log"""
        self.engine = bot_engine
        self.log = bot_engine.log

    async def run_once(self, positions: list):
        """Chạy 1 lần kiểm tra exit. Được gọi từ _run_cycle của BotEngine."""
        try:
            await self._check_open_trades(positions)
            await self._check_entry_opportunities()
        except Exception as e:
            self.log.error(
                f"❌ ExitMonitor lỗi: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )

    async def _get_current_meta(self, symbol: str) -> tuple[float, dict]:
        """
        Lấy giá hiện tại và metadata strategy mới nhất cho symbol.
        Returns: (current_price, metadata_dict)
        """
        from src.core.bot_engine import _normalize_symbol
        trading_symbol = _normalize_symbol(symbol)

        # Lấy signal mới nhất từ cache của engine
        cached = self.engine._last_signals.get(trading_symbol)
        meta = dict(cached.metadata or {}) if cached else {}

        # Lấy giá ticker
        try:
            ticker = await self.engine.exchange.fetch_ticker(trading_symbol)
            price = ticker["last"]
        except Exception:
            price = meta.get("price", 0) or 0

        return price, meta

    async def _check_open_trades(self, positions: list):
        """Kiểm tra các Trade đang mở, đóng nếu điều kiện exit thỏa."""
        async with get_db() as db:
            result = await db.execute(
                select(Trade)
                .options(selectinload(Trade.bot))
                .where(
                    Trade.bot_id == self.engine.bot_id,
                    Trade.status == "filled",
                    Trade.closed_at == None,
                )
            )
            open_trades = result.scalars().all()

        for trade in open_trades:
            try:
                current_price, meta = await self._get_current_meta(trade.symbol)
                if not current_price:
                    continue

                should_exit, reason = _check_exit_condition(
                    strategy_name=trade.strategy or self.engine.strategy_name,
                    signal_type=trade.signal_type or "long",
                    current_price=current_price,
                    entry_price=trade.price or 0,
                    stop_loss=trade.stop_loss if hasattr(trade, 'stop_loss') else 0,
                    take_profit=trade.take_profit if hasattr(trade, 'take_profit') else 0,
                    ohlcv_meta=meta,
                )

                if should_exit:
                    self.log.info(
                        f"🔒 ExitMonitor: Đóng {trade.signal_type.upper()} {trade.symbol} | {reason}"
                    )
                    await self._execute_exit(trade, current_price, reason, positions)

            except Exception as e:
                self.log.error(f"❌ ExitMonitor check trade #{trade.id}: {e}")

    async def _execute_exit(self, trade: Trade, current_price: float, reason: str, positions: list):
        """Thực thi đóng lệnh và cập nhật DB."""
        from src.core.bot_engine import _normalize_symbol
        trading_symbol = _normalize_symbol(trade.symbol)

        # Tìm position trên exchange
        pos_side = trade.signal_type  # "long" | "short"
        amount = None
        for pos in positions:
            sym_clean = pos.get("symbol", "").replace("/", "").replace(":USDT", "")
            if sym_clean == trade.symbol.replace("/", "").replace(":USDT", ""):
                amount = abs(float(pos.get("size", pos.get("contracts", 0))))
                pos_side = pos.get("side", pos_side)
                break

        if not amount:
            self.log.warning(f"ExitMonitor: Không tìm thấy position {trade.symbol} trên exchange")
            return

        try:
            order = await self.engine.exchange.close_position(trading_symbol, pos_side, amount)
            pnl_raw = order.get("info", {}).get("realizedPnl", 0)
            pnl = float(pnl_raw) if pnl_raw else 0.0
            close_price = order.get("average", current_price)

            # Cập nhật DB
            async with get_db() as db:
                result = await db.execute(
                    select(Trade).where(Trade.id == trade.id)
                )
                t = result.scalar_one_or_none()
                if t:
                    t.status = "closed"
                    t.closed_at = datetime.utcnow()
                    t.realized_pnl = pnl

                # Update bot stats
                result2 = await db.execute(select(Bot).where(Bot.id == self.engine.bot_id))
                bot = result2.scalar_one_or_none()
                if bot:
                    bot.total_pnl += pnl
                    if pnl > 0:
                        bot.winning_trades += 1
                    elif pnl < 0:
                        bot.losing_trades += 1

            self.log.info(f"✅ ExitMonitor: Đã đóng {trade.symbol} | PnL: {pnl:+.4f} USDT | {reason}")

            # Discord noti
            embed = build_exit_embed(
                bot_id=self.engine.bot_id,
                signal_type=f"close_{trade.signal_type}",
                symbol=trade.symbol,
                close_price=close_price,
                pnl=pnl,
                reason=f"[ExitMonitor] {reason}",
            )
            await send_discord_message(embed=embed)

        except Exception as e:
            self.log.error(f"❌ ExitMonitor execute_exit {trade.symbol}: {e}\n{traceback.format_exc()}")

    async def _check_entry_opportunities(self):
        """
        Kiểm tra các EntryOpportunity chưa thực thi.
        Nếu điều kiện exit xuất hiện → đánh dấu is_deleted=True.
        """
        async with get_db() as db:
            result = await db.execute(
                select(EntryOpportunity).where(
                    EntryOpportunity.bot_id == self.engine.bot_id,
                    EntryOpportunity.is_deleted == False,
                    EntryOpportunity.executed == False,
                )
            )
            opportunities = result.scalars().all()

        for opp in opportunities:
            try:
                current_price, meta = await self._get_current_meta(opp.symbol)
                if not current_price:
                    continue

                # Merge metadata từ opportunity với metadata mới nhất
                merged_meta = dict(opp.metadata or {})
                merged_meta.update(meta)  # metadata mới nhất override

                should_exit, reason = _check_exit_condition(
                    strategy_name=opp.strategy or self.engine.strategy_name,
                    signal_type=opp.signal_type,
                    current_price=current_price,
                    entry_price=opp.entry_price or 0,
                    stop_loss=opp.stop_loss or 0,
                    take_profit=opp.take_profit or 0,
                    ohlcv_meta=merged_meta,
                )

                if should_exit:
                    self.log.info(
                        f"🗑️ ExitMonitor: Invalidate opportunity #{opp.id} "
                        f"{opp.signal_type.upper()} {opp.symbol} | {reason}"
                    )
                    async with get_db() as db:
                        result = await db.execute(
                            select(EntryOpportunity).where(EntryOpportunity.id == opp.id)
                        )
                        o = result.scalar_one_or_none()
                        if o:
                            o.is_deleted = True
                            o.delete_reason = reason
                            o.invalidated_at = datetime.utcnow()

                    # Noti Discord (channel report)
                    from src.core.discord_notifier import DISCORD_REPORT_WEBHOOK_URL
                    pnl_estimate = (current_price - (opp.entry_price or current_price))
                    if opp.signal_type == "short":
                        pnl_estimate = -pnl_estimate
                    embed = {
                        "title": f"🗑️ Cơ hội hết hạn #{opp.id} — {opp.symbol}",
                        "color": 0x546E7A,
                        "fields": [
                            {"name": "Side", "value": f"`{opp.signal_type.upper()}`", "inline": True},
                            {"name": "Giá entry", "value": f"`{opp.entry_price}`", "inline": True},
                            {"name": "Giá hiện tại", "value": f"`{current_price:.4f}`", "inline": True},
                            {"name": "Lý do", "value": reason[:500], "inline": False},
                        ],
                        "footer": {"text": f"Bot#{self.engine.bot_id} {self.engine.bot_name} — ExitMonitor"},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await send_discord_message(
                        embed=embed,
                        webhook_url=DISCORD_REPORT_WEBHOOK_URL or None
                    )

            except Exception as e:
                self.log.error(f"❌ ExitMonitor check opportunity #{opp.id}: {e}")
