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

    async def process_signal(self, signal: StrategySignal, indicator_data: dict = None) -> bool:
        """
        Xử lý tín hiệu từ strategy
        Returns: True nếu thực thi thành công
        """
        # Lưu signal vào DB
        await self._save_signal(signal, indicator_data)

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

        # Kiểm tra giới hạn số vị thế
        if not self.risk.check_max_positions(positions):
            logger.warning(f"Đã đạt max positions ({self.risk.max_open_positions}), bỏ qua {symbol}")
            return False

        # Lấy thông tin symbol
        try:
            symbol_info = await self.exchange.get_symbol_info(symbol)
        except Exception as e:
            logger.error(f"Không lấy được symbol info {symbol}: {e}")
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
            logger.warning(f"Không thể tạo position plan cho {symbol}")
            return False

        # Đặt leverage và margin mode
        try:
            await self.exchange.set_margin_mode(symbol, self.margin_mode)
            await self.exchange.set_leverage(symbol, plan.leverage)
        except Exception as e:
            logger.warning(f"Lỗi cài đặt leverage/margin: {e}")

        # Đặt lệnh thị trường
        try:
            order = await self.exchange.create_market_order(symbol, side, plan.amount)
            await self._save_trade(order, plan, signal)
            logger.info(
                f"✅ Đã mở {signal.signal.upper()} {symbol} | "
                f"Amount: {plan.amount} | SL: {plan.stop_loss:.4f} | TP: {plan.take_profit:.4f}"
            )
            return True
        except Exception as e:
            logger.error(f"Lỗi đặt lệnh {symbol}: {e}")
            await self._save_failed_trade(symbol, side, plan, signal, str(e))
            return False

    async def _handle_exit(self, signal: StrategySignal, positions: list) -> bool:
        """Đóng vị thế"""
        symbol = signal.symbol
        
        # Tìm vị thế cần đóng
        position = None
        for pos in positions:
            pos_symbol = pos.get("symbol", "").replace("/", "")
            sig_symbol = symbol.replace("/", "")
            if pos_symbol == sig_symbol:
                position = pos
                break

        if not position:
            logger.warning(f"Không tìm thấy vị thế để đóng: {symbol}")
            return False

        pos_side = position.get("side", "long")
        amount = abs(position.get("size", 0))

        if amount <= 0:
            return False

        try:
            order = await self.exchange.close_position(symbol, pos_side, amount)
            logger.info(f"✅ Đã đóng vị thế {pos_side.upper()} {symbol}")
            await self._update_closed_trade(symbol, order)
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
                strategy="ma_macd",
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
                strategy="ma_macd",
            )
            db.add(trade)

    async def _update_closed_trade(self, symbol: str, order: dict):
        """Cập nhật trade khi đóng vị thế"""
        async with get_db() as db:
            # Tìm trade mở gần nhất cho symbol này
            result = await db.execute(
                select(Trade)
                .where(Trade.symbol == symbol, Trade.status == "filled")
                .order_by(Trade.created_at.desc())
                .limit(1)
            )
            trade = result.scalar_one_or_none()
            if trade:
                trade.status = "closed"
                trade.closed_at = datetime.utcnow()

            # Update bot stats
            if getattr(self, 'bot_id', None):
                result2 = await db.execute(select(Bot).where(Bot.id == self.bot_id))
                bot = result2.scalar_one_or_none()
                if bot:
                    pnl = order.get("info", {}).get("realizedPnl", 0)
                    try:
                        pnl = float(pnl)
                        bot.total_pnl += pnl
                        if pnl > 0:
                            bot.winning_trades += 1
                        elif pnl < 0:
                            bot.losing_trades += 1
                    except (ValueError, TypeError):
                        pass
