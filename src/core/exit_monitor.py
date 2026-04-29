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

    elif strategy_name == "sma_macd_cross":
        ma_color   = ohlcv_meta.get("ma_color", "")
        sig_color  = ohlcv_meta.get("sig_color", "")
        macd_color = ohlcv_meta.get("macd_color", "")
        close_val  = ohlcv_meta.get("close", current_price)
        ma_val     = ohlcv_meta.get("ma", 0)

        BULLISH = {"blue", "green"}
        BEARISH = {"red", "orange"}

        if signal_type == "long":
            if ma_val and close_val < ma_val:
                return True, f"📉 Giá đóng cửa dưới MA ({close_val:.4f} < {ma_val:.4f})"
            if ma_color in BEARISH:
                return True, f"📉 MA chuyển {ma_color}"
            if sig_color in BEARISH:
                return True, f"📉 MACD-Signal chuyển {sig_color}"
            if macd_color == "red" and ma_color == "green":
                return True, f"📉 MACD đỏ + MA xanh lá (phân kỳ giảm)"
        elif signal_type == "short":
            if ma_val and close_val > ma_val:
                return True, f"📈 Giá đóng cửa trên MA ({close_val:.4f} > {ma_val:.4f})"
            if ma_color in BULLISH:
                return True, f"📈 MA chuyển {ma_color}"
            if sig_color in BULLISH:
                return True, f"📈 MACD-Signal chuyển {sig_color}"
            if macd_color == "blue" and ma_color == "orange":
                return True, f"📈 MACD xanh dương + MA cam (phân kỳ tăng)"

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
        Ưu tiên fetch OHLCV mới để tính indicator, fallback về cache signal.
        Returns: (current_price, metadata_dict)
        """
        from src.core.bot_engine import _normalize_symbol
        from src.data.indicators import add_custom_sma_to_df
        import pandas as pd

        trading_symbol = _normalize_symbol(symbol)

        # Lấy giá ticker
        current_price = 0.0
        try:
            ticker = await self.engine.exchange.fetch_ticker(trading_symbol)
            current_price = ticker["last"]
        except Exception:
            pass

        # Thử lấy metadata từ OHLCV mới nhất để có trend/momentum chính xác
        try:
            ohlcv = await self.engine.exchange.fetch_ohlcv(
                trading_symbol, self.engine.timeframe, 60
            )
            if ohlcv and len(ohlcv) >= 10:
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df = add_custom_sma_to_df(df)
                if not current_price:
                    current_price = float(df["close"].iloc[-1])

                meta = {
                    "trend": int(df["custom_sma_trend"].iloc[-1]),
                    "prev_trend": int(df["custom_sma_trend"].iloc[-2]),
                    "momentum": str(df["custom_sma_momentum"].iloc[-1]),
                    "slope_pct": float(df["custom_sma_slope_pct"].iloc[-1]),
                    "momentum_pct": float(df["custom_sma_momentum_pct"].iloc[-1]),
                    "is_sideway": abs(float(df["custom_sma_slope_pct"].iloc[-1])) < self.engine.parameters.get("sideway_slope_threshold", 0.01),
                }

                # Thêm MACD fields cho sma_macd_cross
                if self.engine.strategy_name == "sma_macd_cross":
                    try:
                        from src.data.indicators import add_custom_macd_to_df
                        p = self.engine.parameters
                        df = add_custom_macd_to_df(
                            df,
                            fast=p.get("macd_fast", 12),
                            slow=p.get("macd_slow", 26),
                            signal_length=p.get("macd_signal_length", 500),
                            src=p.get("macd_src", "EMA"),
                            sig_type=p.get("macd_sig_type", "EMA"),
                        )
                        # Tính màu slope cho MA, MACD, Signal
                        def _sc(c, p2, o):
                            if c == p2: return "yellow"
                            sc = c - p2; sp = p2 - o
                            if c > p2: return "blue" if sc >= sp else "green"
                            else: return "red" if sc <= sp else "orange"

                        ma_arr  = df["custom_sma_basis"].to_numpy()
                        sig_arr = df["custom_macd_signal"].to_numpy()
                        mac_arr = df["custom_macd"].to_numpy()
                        i = len(df) - 1
                        meta["ma_color"]   = _sc(ma_arr[i],  ma_arr[i-1],  ma_arr[i-2])
                        meta["sig_color"]  = _sc(sig_arr[i], sig_arr[i-1], sig_arr[i-2])
                        meta["macd_color"] = _sc(mac_arr[i], mac_arr[i-1], mac_arr[i-2])
                        meta["ma"]         = float(ma_arr[i])
                        meta["macd"]       = float(mac_arr[i])
                        meta["macd_signal"] = float(sig_arr[i])
                        meta["close"]      = float(df["close"].iloc[-1])
                    except Exception as e_macd:
                        self.log.debug(f"ExitMonitor MACD meta error: {e_macd}")

                return current_price, meta
        except Exception as e:
            self.log.debug(f"ExitMonitor _get_current_meta fallback to cache: {e}")

        # Fallback: dùng cache signal
        cached = self.engine._last_signals.get(trading_symbol)
        if cached and cached.metadata:
            raw = cached.metadata
            meta = dict(raw) if isinstance(raw, dict) else {}
        else:
            meta = {}
        return current_price, meta

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
                opp_meta = opp.metadata
                if opp_meta is None:
                    opp_meta = {}
                elif not isinstance(opp_meta, dict):
                    try:
                        opp_meta = dict(opp_meta)
                    except Exception:
                        opp_meta = {}
                merged_meta = dict(opp_meta)
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
