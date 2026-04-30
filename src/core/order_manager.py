"""
order_manager.py — Order Execution và Management
Thực thi các tín hiệu từ strategy, lưu vào database
"""
from datetime import datetime
from loguru import logger

from src.core.exchange import BinanceExchange
from src.core.risk_manager import RiskManager, PositionPlan
from src.strategies.base_strategy import StrategySignal
from src.database.db import get_db
from src.database.models import Trade, Signal, Bot
from sqlalchemy import select

from src.core.discord_notifier import (
    send_discord_message,
    build_entry_embed,
    build_exit_embed,
    build_error_embed,
)


class OrderManager:
    """
    Nhận StrategySignal → Tính position size → Đặt lệnh → Lưu DB
    """

    def __init__(self, exchange: BinanceExchange, risk_manager: RiskManager, config: dict):
        self.exchange = exchange
        self.risk = risk_manager
        self.config = config
        self.leverage = config.get("leverage", 5)
        self.margin_mode = config.get("margin_mode", "isolated")
        # strategy_name lấy từ bot_engine khi khởi tạo
        self.strategy_name: str = "unknown"
        # effective_max được set bởi bot_engine trước mỗi lần process_signal
        self.effective_max_positions: int = None

    async def process_signal(self, signal: StrategySignal, indicator_data: dict = None) -> bool:
        """
        Xử lý tín hiệu từ strategy
        Returns: True nếu thực thi thành công
        """
        # Chỉ lưu signal entry/exit vào DB, bỏ qua "none" để tránh spam
        if not signal.is_none:
            try:
                await self._save_signal(signal, indicator_data)
            except Exception as e:
                logger.warning(f"Lỗi lưu signal DB (bỏ qua): {e}")

        if signal.is_none:
            return False

        # Lấy thông tin thị trường
        try:
            balance = await self.exchange.get_balance()
            positions = await self.exchange.get_positions()
        except Exception as e:
            logger.error(f"Lỗi lấy account info: {e}")
            return False

        # Xử lý lệnh CLOSE
        if signal.is_exit:
            return await self._handle_exit(signal, positions)

        # Xử lý lệnh ENTRY
        if signal.is_entry:
            return await self._handle_entry(signal, balance, positions)

        return False

    async def _handle_entry(self, signal: StrategySignal, balance: dict, positions: list) -> bool:
        """Mở vị thế mới"""
        symbol = signal.symbol
        free_balance = balance.get("free", 0)

        logger.info(f"[Entry] {signal.signal.upper()} {symbol} | Số dư: ${free_balance:.2f} USDT | Giá: {signal.price}")

        # Kiểm tra giới hạn số vị thế (safety net — đã check ở bot_engine rồi)
        if not self.risk.check_max_positions(positions, self.effective_max_positions):
            limit = self.effective_max_positions or self.risk.max_open_positions
            logger.warning(f"[Entry] Đã đạt max positions ({limit}), bỏ qua {symbol}")
            return False

        if free_balance <= 0:
            logger.error(f"[Entry] Số dư = 0, không thể đặt lệnh {symbol}")
            return False

        # Lấy thông tin symbol
        try:
            symbol_info = await self.exchange.get_symbol_info(symbol)
        except Exception as e:
            logger.error(f"[Entry] Không lấy được symbol info {symbol}: {e}")
            return False

        # Tính kế hoạch lệnh
        side = "buy" if signal.signal == "long" else "sell"
        plan = self.risk.calculate_position(
            balance_usdt=free_balance,
            entry_price=signal.price,
            side=side,
            symbol=symbol,
            min_amount=symbol_info.get("min_amount", 0.001),
            amount_precision=symbol_info.get("amount_precision", 3),
        )

        if plan is None:
            logger.warning(f"[Entry] Không thể tạo position plan cho {symbol} (amount < min hoặc số dư quá nhỏ)")
            return False

        logger.info(f"[Entry] Plan: {side.upper()} {plan.amount} {symbol} @ {plan.entry_price} | Leverage: {plan.leverage}x")

        # Đặt leverage và margin mode
        try:
            await self.exchange.set_margin_mode(symbol, self.margin_mode)
            await self.exchange.set_leverage(symbol, plan.leverage)
        except Exception as e:
            logger.warning(f"[Entry] Lỗi cài đặt leverage/margin (tiếp tục): {e}")

        # Đặt lệnh thị trường
        try:
            order = await self.exchange.create_market_order(symbol, side, plan.amount)
            await self._save_trade(order, plan, signal)
            logger.info(
                f"✅ Đã mở {signal.signal.upper()} {symbol} | "
                f"Amount: {plan.amount} | SL: {plan.stop_loss:.4f} | TP: {plan.take_profit:.4f}"
            )

            # Gửi thông báo Discord — luôn gửi khi đặt lệnh thực tế thành công
            # (notify_entry chỉ ảnh hưởng đến noti khi bị chặn, không ảnh hưởng lệnh thật)
            embed = build_entry_embed(
                bot_id=getattr(self, 'bot_id', '?'),
                signal_type=signal.signal,
                symbol=symbol,
                entry_price=plan.entry_price,
                amount=plan.amount,
                leverage=plan.leverage,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
                reason=signal.reason,
            )
            await send_discord_message(embed=embed)

            return True
        except Exception as e:
            logger.error(f"Lỗi đặt lệnh {symbol}: {e}")
            await self._save_failed_trade(symbol, side, plan, signal, str(e))
            # Thông báo lỗi lên Discord
            await send_discord_message(embed=build_error_embed(
                bot_id=getattr(self, 'bot_id', '?'), symbol=symbol, error=str(e)
            ))
            return False

    async def _handle_exit(self, signal: StrategySignal, positions: list) -> bool:
        """Đóng vị thế theo chế độ cách ly (isolated per-trade).
        
        Dùng trade.amount từ DB thay vì toàn bộ position size từ exchange,
        đảm bảo mỗi bot chỉ đóng đúng phần lệnh của mình.
        """
        symbol = signal.symbol
        bot_id = getattr(self, 'bot_id', None)

        # Lấy Trade record từ DB để biết đúng amount của bot này
        trade_record = None
        async with get_db() as db:
            query = (
                select(Trade)
                .where(
                    Trade.symbol == symbol,
                    Trade.status == "filled",
                    Trade.closed_at == None,
                )
            )
            if bot_id:
                query = query.where(Trade.bot_id == bot_id)
            query = query.order_by(Trade.created_at.desc()).limit(1)
            result = await db.execute(query)
            trade_record = result.scalar_one_or_none()

        # Lấy pos_side từ exchange (cần biết hướng để đóng đúng chiều)
        pos_side = "long"  # fallback
        exchange_amount = None
        for pos in positions:
            pos_symbol = pos.get("symbol", "").replace("/", "")
            sig_symbol = symbol.replace("/", "")
            if pos_symbol == sig_symbol:
                pos_side = pos.get("side", "long")
                exchange_amount = abs(float(pos.get("size", 0)))
                break

        if exchange_amount is None or exchange_amount <= 0:
            logger.warning(f"Không tìm thấy vị thế để đóng: {symbol}")
            return False

        # Dùng trade.amount (isolated), fallback về exchange amount nếu không có record
        if trade_record and trade_record.amount and trade_record.amount > 0:
            amount = trade_record.amount
            # Cap lại nếu vượt quá remaining position (partial fill, manual close, ...)
            if amount > exchange_amount:
                logger.warning(
                    f"[Exit] trade amount={amount} > exchange position={exchange_amount} "
                    f"cho {symbol}, cap lại về {exchange_amount}"
                )
                amount = exchange_amount
        else:
            # Không có trade record → fallback về exchange amount (backward compat)
            logger.warning(
                f"[Exit] Không tìm thấy trade record cho {symbol} bot#{bot_id}, "
                f"dùng exchange amount={exchange_amount}"
            )
            amount = exchange_amount

        try:
            order = await self.exchange.close_position(symbol, pos_side, amount)
            logger.info(
                f"✅ Đã đóng vị thế {pos_side.upper()} {symbol} | "
                f"amount={amount} (isolated) | bot#{bot_id}"
            )
            # Cập nhật đúng trade record của bot này
            if trade_record:
                await self._update_closed_trade_by_id(trade_record.id, order)
            else:
                await self._update_closed_trade(symbol, order)

            pnl = order.get("info", {}).get("realizedPnl", "0")
            close_price = order.get("average", signal.price)

            # Thông báo Discord
            embed = build_exit_embed(
                bot_id=bot_id or '?',
                signal_type=signal.signal,
                symbol=symbol,
                close_price=close_price,
                pnl=pnl,
                reason=signal.reason,
            )
            await send_discord_message(embed=embed)

            return True
        except Exception as e:
            logger.error(f"Lỗi đóng vị thế {symbol}: {e}")
            return False

    async def _save_signal(self, signal: StrategySignal, indicator_data: dict = None):
        """Lưu signal vào database"""
        ind = indicator_data or {}
        async with get_db() as db:
            sig = Signal(
                bot_id=getattr(self, 'bot_id', None),
                symbol=signal.symbol,
                signal_type=signal.signal,
                price=signal.price,
                ma_fast=ind.get("ma_fast"),
                ma_slow=ind.get("ma_slow"),
                macd=ind.get("macd"),
                macd_signal=ind.get("macd_signal"),
                macd_histogram=ind.get("macd_histogram"),
                executed=signal.is_entry or signal.is_exit,
            )
            db.add(sig)

    async def _save_trade(self, order: dict, plan: PositionPlan, signal: StrategySignal):
        """Lưu trade thành công vào database"""
        async with get_db() as db:
            trade = Trade(
                bot_id=getattr(self, 'bot_id', None),
                order_id=str(order.get("id", "")),
                symbol=plan.symbol,
                side=plan.side,
                order_type="market",
                amount=plan.amount,
                price=plan.entry_price,
                avg_price=order.get("average") or plan.entry_price,
                cost=order.get("cost") or plan.usdt_value,
                status="filled",
                signal_type=signal.signal,
                leverage=plan.leverage,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
                strategy=self.strategy_name,
                signal_metadata=signal.metadata if isinstance(signal.metadata, dict) else {},
            )
            db.add(trade)

            # Update bot stats
            if getattr(self, 'bot_id', None):
                result = await db.execute(select(Bot).where(Bot.id == self.bot_id))
                bot_status = result.scalar_one_or_none()
                if bot_status:
                        bot_status.total_trades += 1

    async def _save_failed_trade(self, symbol: str, side: str, plan: PositionPlan,
                                  signal: StrategySignal, error: str):
        """Lưu trade thất bại vào database"""
        async with get_db() as db:
            trade = Trade(
                bot_id=getattr(self, 'bot_id', None),
                order_id=f"failed_{datetime.utcnow().timestamp()}",
                symbol=symbol,
                side=side,
                amount=plan.amount,
                price=plan.entry_price,
                status="failed",
                signal_type=signal.signal,
                strategy=self.strategy_name,
            )
            db.add(trade)

    async def _update_closed_trade(self, symbol: str, order: dict):
        """Cập nhật trade khi đóng vị thế (fallback — tìm theo symbol)"""
        async with get_db() as db:
            # Tìm trade mở gần nhất cho symbol này
            result = await db.execute(
                select(Trade)
                .where(Trade.symbol == symbol, Trade.status == "filled")
                .order_by(Trade.created_at.desc())
                .limit(1)
            )
            trade = result.scalar_one_or_none()

            pnl_raw = order.get("info", {}).get("realizedPnl", 0)
            try:
                pnl = float(pnl_raw)
            except (ValueError, TypeError):
                pnl = 0.0

            if trade:
                trade.status = "closed"
                trade.closed_at = datetime.utcnow()
                trade.realized_pnl = pnl

            # Update bot stats
            if getattr(self, 'bot_id', None):
                result2 = await db.execute(select(Bot).where(Bot.id == self.bot_id))
                bot = result2.scalar_one_or_none()
                if bot:
                    bot.total_pnl += pnl
                    if pnl > 0:
                        bot.winning_trades += 1
                    elif pnl < 0:
                        bot.losing_trades += 1

    async def _update_closed_trade_by_id(self, trade_id: int, order: dict):
        """Cập nhật trade khi đóng vị thế — theo trade ID cụ thể (isolated mode)"""
        pnl_raw = order.get("info", {}).get("realizedPnl", 0)
        try:
            pnl = float(pnl_raw)
        except (ValueError, TypeError):
            pnl = 0.0

        async with get_db() as db:
            result = await db.execute(select(Trade).where(Trade.id == trade_id))
            trade = result.scalar_one_or_none()
            if trade:
                trade.status = "closed"
                trade.closed_at = datetime.utcnow()
                trade.realized_pnl = pnl

            # Update bot stats
            if getattr(self, 'bot_id', None):
                result2 = await db.execute(select(Bot).where(Bot.id == self.bot_id))
                bot = result2.scalar_one_or_none()
                if bot:
                    bot.total_pnl += pnl
                    if pnl > 0:
                        bot.winning_trades += 1
                    elif pnl < 0:
                        bot.losing_trades += 1
