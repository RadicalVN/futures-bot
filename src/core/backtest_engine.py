"""
backtest_engine.py — Strategy-Agnostic Backtesting Engine.

Cơ chế cốt lõi (Parity First):
  - Dùng StrategyFactory để khởi tạo strategy — không if/elif hardcode.
  - Loop qua từng nến, gọi strategy.analyze(ohlcv_slice, sim_positions).
  - Sliding window: ohlcv_slice = all_candles[i-lookback+1 : i+1].
  - Mô phỏng đầy đủ current_positions (vị thế ảo) để truyền vào analyze().

Partial Close Support:
  - Xử lý metadata["partial_close"] từ signal (TP1, Emergency Exit).
  - Cập nhật amount_remaining và balance từng phần.

Shared Analytics:
  - Dùng src.core.analytics.calc_trade_metrics() — math giống Live Trading.

Tuân thủ ARCHITECTURE_GUIDELINES.md:
  - Zero-Core-Edit: không sửa bot_engine.py hay bất kỳ file core nào.
  - App-Isolation: không import từ src.apps.
  - Type Hinting 100%, Google-style Docstrings, ≤50 dòng/hàm.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from src.core.analytics import TradeMetrics, calc_trade_metrics, calc_max_drawdown_from_equity
from src.strategies.factory import StrategyFactory
from src.strategies.base_strategy import StrategySignal


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """Cấu hình cho một lần chạy backtest.

    Attributes:
        strategy_name: Tên strategy (khớp với STRATEGY_NAME trong registry).
        parameters: Dict tham số của strategy (giống Bot.parameters).
        symbol: Symbol giao dịch (vd: "BTC/USDT").
        initial_balance: Số dư ban đầu (USDT).
        leverage: Đòn bẩy.
        position_size_pct: Tỷ lệ vốn mỗi lệnh (0.0–1.0).
        commission_pct: Tỷ lệ phí giao dịch (vd: 0.0005 = 0.05%).
        slippage_pct: Tỷ lệ trượt giá (vd: 0.0002 = 0.02%).
    """
    strategy_name:     str
    parameters:        dict
    symbol:            str            = "BTC/USDT"
    initial_balance:   float          = 10000.0
    leverage:          int            = 5
    position_size_pct: float          = 0.10
    commission_pct:    float          = 0.0005
    slippage_pct:      float          = 0.0


# ── Virtual Position ──────────────────────────────────────────────────────────

@dataclass
class VirtualPosition:
    """Vị thế ảo trong backtest — tương thích với ADTS v1.5.

    Attributes:
        symbol: Symbol giao dịch.
        side: "long" hoặc "short".
        entry_price: Giá vào lệnh.
        amount: Khối lượng hiện tại (sau partial close).
        amount_total: Khối lượng ban đầu.
        position_value: Giá trị vị thế (USDT, có leverage).
        stop_loss: Giá stop loss.
        take_profit: Giá take profit.
        opened_at: Timestamp mở lệnh (ms).
        tp1_hit: Đã chốt TP1 chưa (ADTS).
        sl_moved_to_entry: SL đã dời về entry chưa (ADTS).
        emergency_triggered: Emergency Exit Giai đoạn 1 đã kích hoạt chưa (ADTS).
        metadata: Metadata từ entry signal.
    """
    symbol:              str
    side:                str
    entry_price:         float
    amount:              float
    amount_total:        float
    position_value:      float
    stop_loss:           float
    take_profit:         float
    opened_at:           int
    tp1_hit:             bool  = False
    sl_moved_to_entry:   bool  = False
    emergency_triggered: bool  = False
    metadata:            dict  = field(default_factory=dict)

    def to_exchange_format(self) -> dict:
        """Chuyển sang format giống exchange.get_positions() để truyền vào analyze().

        Returns:
            Dict tương thích với current_positions trong strategy.analyze().
        """
        return {
            "symbol":       self.symbol,
            "side":         self.side,
            "contracts":    self.amount,
            "size":         self.amount,
            "entry_price":  self.entry_price,
            "metadata":     self.metadata,
        }


# ── Trade Record ──────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """Bản ghi một lệnh đã đóng trong backtest.

    Attributes:
        entry_ts: Timestamp mở lệnh (ms).
        exit_ts: Timestamp đóng lệnh (ms).
        side: "long" hoặc "short".
        entry_price: Giá vào lệnh.
        exit_price: Giá đóng lệnh.
        amount: Khối lượng đóng.
        pnl_gross: PnL trước phí (USDT).
        commission: Phí giao dịch (USDT).
        pnl_net: PnL ròng sau phí (USDT).
        reason: Lý do đóng lệnh (từ signal.reason).
        is_partial: True nếu là partial close (TP1, Emergency).
    """
    entry_ts:    int
    exit_ts:     int
    side:        str
    entry_price: float
    exit_price:  float
    amount:      float
    pnl_gross:   float
    commission:  float
    pnl_net:     float
    reason:      str
    is_partial:  bool = False

    @property
    def duration_hours(self) -> float:
        """Thời gian giữ lệnh (giờ)."""
        return (self.exit_ts - self.entry_ts) / 3_600_000


# ── Backtest Result ───────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """Kết quả đầy đủ của một lần chạy backtest.

    Attributes:
        config: Cấu hình backtest đã dùng.
        trades: Danh sách tất cả lệnh đã đóng (bao gồm partial).
        equity_curve: Dense equity curve [{ts, equity}] tại mỗi nến.
        metrics: Các chỉ số hiệu suất tổng hợp.
        start_ts: Timestamp bắt đầu backtest (ms).
        end_ts: Timestamp kết thúc backtest (ms).
        total_candles: Số nến đã simulate.
    """
    config:        BacktestConfig
    trades:        list[TradeRecord]
    equity_curve:  list[dict]
    metrics:       TradeMetrics
    start_ts:      int
    end_ts:        int
    total_candles: int

    def to_dict(self) -> dict:
        """Chuyển sang dict JSON-serializable cho API response.

        Returns:
            Dict đầy đủ kết quả backtest.
        """
        return {
            "strategy_name":   self.config.strategy_name,
            "symbol":          self.config.symbol,
            "initial_balance": self.config.initial_balance,
            "start_ts":        self.start_ts,
            "end_ts":          self.end_ts,
            "total_candles":   self.total_candles,
            "total_trades":    len(self.trades),
            "metrics":         self.metrics.to_dict(),
            "equity_curve":    self.equity_curve,
            "trades": [
                {
                    "entry_ts":    t.entry_ts,
                    "exit_ts":     t.exit_ts,
                    "side":        t.side,
                    "entry_price": t.entry_price,
                    "exit_price":  t.exit_price,
                    "amount":      t.amount,
                    "pnl_gross":   t.pnl_gross,
                    "commission":  t.commission,
                    "pnl_net":     t.pnl_net,
                    "reason":      t.reason,
                    "is_partial":  t.is_partial,
                    "duration_h":  round(t.duration_hours, 2),
                }
                for t in self.trades
            ],
        }


# ── BacktestEngine ────────────────────────────────────────────────────────────

class BacktestEngine:
    """Strategy-agnostic backtesting engine.

    Gọi strategy.analyze() cho từng nến — đảm bảo parity với live trading.
    Hỗ trợ partial close (TP1, Emergency Exit) và dense equity curve.

    Example:
        config = BacktestConfig(
            strategy_name="adts",
            parameters={"adx_threshold": 20.0, "leverage": 5},
            symbol="BTC/USDT",
            initial_balance=10000.0,
        )
        engine = BacktestEngine(config)
        result = await engine.run(ohlcv_df)
        print(result.metrics.win_rate_pct)
    """

    def __init__(self, config: BacktestConfig) -> None:
        """Khởi tạo BacktestEngine với config.

        Args:
            config: BacktestConfig chứa tất cả tham số backtest.
        """
        self._config   = config
        self._strategy = StrategyFactory.create(config.strategy_name, config.parameters)
        self._lookback = max(
            config.parameters.get("lookback_candles", 200),
            self._strategy.get_required_lookback(config.parameters),
        )
        logger.info(
            f"[BacktestEngine] Init | strategy={config.strategy_name} "
            f"| symbol={config.symbol} | lookback={self._lookback}"
        )

    async def run(
        self,
        ohlcv_data: list | pd.DataFrame,
        start_ts:   Optional[int] = None,
        end_ts:     Optional[int] = None,
    ) -> BacktestResult:
        """Chạy backtest trên dữ liệu OHLCV.

        Args:
            ohlcv_data: Dữ liệu OHLCV dạng list [[ts_ms, o, h, l, c, v], ...]
                hoặc DataFrame với columns [timestamp, open, high, low, close, volume].
            start_ts: Timestamp bắt đầu simulate (ms). None = từ nến lookback.
            end_ts: Timestamp kết thúc simulate (ms). None = đến nến cuối.

        Returns:
            BacktestResult với trades, equity_curve và metrics.

        Raises:
            ValueError: Nếu không đủ dữ liệu để simulate.
        """
        candles = self._normalize_input(ohlcv_data)
        if len(candles) < self._lookback + 1:
            raise ValueError(
                f"Không đủ dữ liệu: có {len(candles)} nến, "
                f"cần ≥{self._lookback + 1} (lookback={self._lookback})"
            )

        start_idx, end_idx = self._resolve_range(candles, start_ts, end_ts)
        logger.info(
            f"[BacktestEngine] Simulate {end_idx - start_idx} nến "
            f"({start_idx}→{end_idx}) | lookback={self._lookback}"
        )

        trades, equity_curve = await self._simulate_loop(candles, start_idx, end_idx)
        metrics = self._build_metrics(trades, equity_curve)

        return BacktestResult(
            config=self._config,
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
            start_ts=candles[start_idx][0],
            end_ts=candles[end_idx - 1][0],
            total_candles=end_idx - start_idx,
        )

    # ── Core simulation loop ──────────────────────────────────────────────────

    async def _simulate_loop(
        self,
        candles:   list,
        start_idx: int,
        end_idx:   int,
    ) -> tuple[list[TradeRecord], list[dict]]:
        """Vòng lặp simulate chính — gọi strategy.analyze() cho từng nến.

        Sliding window: ohlcv_slice = candles[i-lookback+1 : i+1].
        Không pre-compute indicators — đảm bảo parity với live trading.

        Args:
            candles: Toàn bộ dữ liệu OHLCV dạng list.
            start_idx: Index nến bắt đầu simulate.
            end_idx: Index nến kết thúc simulate (exclusive).

        Returns:
            Tuple (trades, equity_curve).
        """
        balance:      float                    = self._config.initial_balance
        open_pos:     Optional[VirtualPosition] = None
        trades:       list[TradeRecord]         = []
        equity_curve: list[dict]                = []
        total         = end_idx - start_idx

        for loop_idx in range(start_idx, end_idx):
            candle = candles[loop_idx]

            # Sliding window — không look-ahead
            slice_start = max(0, loop_idx - self._lookback + 1)
            ohlcv_slice = candles[slice_start : loop_idx + 1]

            sim_positions = [open_pos.to_exchange_format()] if open_pos else []

            try:
                signal = await self._strategy.analyze(
                    self._config.symbol, ohlcv_slice, sim_positions
                )
            except Exception as exc:
                logger.warning(
                    f"[BacktestEngine] strategy.analyze lỗi tại nến {loop_idx}: "
                    f"{type(exc).__name__}: {exc}"
                )
                signal = StrategySignal(signal="none", symbol=self._config.symbol, price=0, reason="error")

            # Xử lý signal
            if signal.is_exit and open_pos is not None:
                new_trades, balance, open_pos = self._process_exit(
                    signal, candle, open_pos, balance
                )
                trades.extend(new_trades)
            elif signal.is_entry and open_pos is None:
                open_pos = self._process_entry(signal, candle, balance)

            # Dense equity curve — ghi nhận tại mỗi nến
            equity_curve.append(self._calc_equity_point(candle, balance, open_pos))

            if total > 0 and loop_idx % max(1, total // 20) == 0:
                logger.debug(
                    f"[BacktestEngine] {loop_idx - start_idx + 1}/{total} nến | "
                    f"balance={balance:.2f} | trades={len(trades)}"
                )

        # Đóng vị thế còn mở ở nến cuối
        if open_pos is not None:
            last_candle = candles[end_idx - 1]
            close_signal = StrategySignal(
                signal=f"close_{open_pos.side}",
                symbol=self._config.symbol,
                price=last_candle[4],
                reason="Backtest end — force close",
            )
            new_trades, balance, _ = self._process_exit(
                close_signal, last_candle, open_pos, balance
            )
            trades.extend(new_trades)

        return trades, equity_curve

    # ── Entry / Exit handlers ─────────────────────────────────────────────────

    def _process_entry(
        self,
        signal: StrategySignal,
        candle: list,
        balance: float,
    ) -> VirtualPosition:
        """Tạo vị thế ảo khi nhận entry signal.

        Áp dụng slippage tại thời điểm khớp lệnh.

        Args:
            signal: StrategySignal với signal="long" hoặc "short".
            candle: Nến hiện tại [ts, o, h, l, c, v].
            balance: Số dư hiện tại (USDT).

        Returns:
            VirtualPosition mới.
        """
        raw_price  = signal.price if signal.price > 0 else candle[4]
        entry_price = self._apply_slippage(raw_price, signal.signal)

        position_value = balance * self._config.position_size_pct * self._config.leverage
        amount         = position_value / entry_price if entry_price > 0 else 0.0

        meta = signal.metadata or {}
        return VirtualPosition(
            symbol=self._config.symbol,
            side=signal.signal,
            entry_price=entry_price,
            amount=amount,
            amount_total=amount,
            position_value=position_value,
            stop_loss=float(meta.get("stop_loss", 0.0)),
            take_profit=float(meta.get("take_profit_1", 0.0)),
            opened_at=candle[0],
            metadata=meta,
        )

    def _process_exit(
        self,
        signal:   StrategySignal,
        candle:   list,
        open_pos: VirtualPosition,
        balance:  float,
    ) -> tuple[list[TradeRecord], float, Optional[VirtualPosition]]:
        """Xử lý exit signal — hỗ trợ partial close.

        Đọc metadata["partial_close"] và metadata["partial_pct"] để xử lý
        TP1, Emergency Exit Giai đoạn 1 (partial) và full close.

        Args:
            signal: StrategySignal với signal="close_long" hoặc "close_short".
            candle: Nến hiện tại [ts, o, h, l, c, v].
            open_pos: Vị thế ảo đang mở.
            balance: Số dư hiện tại (USDT).

        Returns:
            Tuple (new_trades, new_balance, remaining_position).
            remaining_position = None nếu full close.
        """
        meta        = signal.metadata or {}
        is_partial  = bool(meta.get("partial_close", False))
        partial_pct = float(meta.get("partial_pct", 1.0))
        full_close  = bool(meta.get("full_close", not is_partial))

        exit_price  = signal.price if signal.price > 0 else candle[4]
        close_amount = open_pos.amount * partial_pct if is_partial else open_pos.amount

        trade = self._calc_trade_record(
            open_pos=open_pos,
            exit_price=exit_price,
            close_amount=close_amount,
            exit_ts=candle[0],
            reason=signal.reason,
            is_partial=is_partial,
        )
        new_balance = balance + trade.pnl_net

        # Cập nhật ADTS state flags từ metadata
        if is_partial and not full_close:
            open_pos.amount -= close_amount
            if meta.get("tp1_hit"):
                open_pos.tp1_hit = True
                open_pos.sl_moved_to_entry = True
            if meta.get("emergency_triggered") or "Emergency" in signal.reason:
                open_pos.emergency_triggered = True
            remaining = open_pos
        else:
            remaining = None

        return [trade], new_balance, remaining

    # ── Calculation helpers ───────────────────────────────────────────────────

    def _calc_trade_record(
        self,
        open_pos:     VirtualPosition,
        exit_price:   float,
        close_amount: float,
        exit_ts:      int,
        reason:       str,
        is_partial:   bool,
    ) -> TradeRecord:
        """Tính PnL và phí cho một lệnh đóng.

        Công thức Futures USDT-M:
            LONG:  pnl_gross = (exit - entry) * amount
            SHORT: pnl_gross = (entry - exit) * amount
            commission = (entry * amount + exit * amount) * commission_pct
            pnl_net = pnl_gross - commission

        Args:
            open_pos: Vị thế ảo đang đóng.
            exit_price: Giá đóng lệnh.
            close_amount: Khối lượng đóng.
            exit_ts: Timestamp đóng lệnh (ms).
            reason: Lý do đóng lệnh.
            is_partial: True nếu là partial close.

        Returns:
            TradeRecord với đầy đủ thông tin PnL.
        """
        if open_pos.side == "long":
            pnl_gross = (exit_price - open_pos.entry_price) * close_amount
        else:
            pnl_gross = (open_pos.entry_price - exit_price) * close_amount

        commission = (
            open_pos.entry_price * close_amount
            + exit_price * close_amount
        ) * self._config.commission_pct

        return TradeRecord(
            entry_ts=open_pos.opened_at,
            exit_ts=exit_ts,
            side=open_pos.side,
            entry_price=open_pos.entry_price,
            exit_price=exit_price,
            amount=close_amount,
            pnl_gross=round(pnl_gross, 6),
            commission=round(commission, 6),
            pnl_net=round(pnl_gross - commission, 6),
            reason=reason,
            is_partial=is_partial,
        )

    def _apply_slippage(self, price: float, side: str) -> float:
        """Áp dụng slippage vào giá entry.

        Long → mua cao hơn (bất lợi).
        Short → bán thấp hơn (bất lợi).

        Args:
            price: Giá tín hiệu.
            side: "long" hoặc "short".

        Returns:
            Giá sau slippage.
        """
        if self._config.slippage_pct <= 0:
            return price
        if side == "long":
            return price * (1.0 + self._config.slippage_pct)
        return price * (1.0 - self._config.slippage_pct)

    def _calc_equity_point(
        self,
        candle:   list,
        balance:  float,
        open_pos: Optional[VirtualPosition],
    ) -> dict:
        """Tính equity tại nến hiện tại (bao gồm unrealized PnL).

        Args:
            candle: Nến hiện tại [ts, o, h, l, c, v].
            balance: Số dư đã realized.
            open_pos: Vị thế ảo đang mở (None nếu không có).

        Returns:
            Dict {"ts": int, "equity": float}.
        """
        unrealized = 0.0
        if open_pos is not None and open_pos.entry_price > 0:
            close = candle[4]
            if open_pos.side == "long":
                unrealized = (close - open_pos.entry_price) * open_pos.amount
            else:
                unrealized = (open_pos.entry_price - close) * open_pos.amount
        return {"ts": candle[0], "equity": round(balance + unrealized, 4)}

    # ── Metrics builder ───────────────────────────────────────────────────────

    def _build_metrics(
        self,
        trades:       list[TradeRecord],
        equity_curve: list[dict],
    ) -> TradeMetrics:
        """Tính toán metrics từ trades và equity curve.

        Dùng src.core.analytics.calc_trade_metrics() — shared math engine.

        Args:
            trades: Danh sách TradeRecord đã đóng.
            equity_curve: Dense equity curve từ simulate loop.

        Returns:
            TradeMetrics với đầy đủ chỉ số.
        """
        pnl_list        = [t.pnl_net for t in trades]
        durations       = [t.duration_hours for t in trades]
        commission_list = [t.commission for t in trades]
        eq_values       = [p["equity"] for p in equity_curve]

        return calc_trade_metrics(
            pnl_list=pnl_list,
            durations_hours=durations,
            commission_list=commission_list,
            equity_curve=eq_values,
        )

    # ── Input normalization ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_input(ohlcv_data: list | pd.DataFrame) -> list:
        """Chuẩn hóa input về dạng list [[ts_ms, o, h, l, c, v], ...].

        Hỗ trợ cả list (từ exchange/cache) và DataFrame (từ DB cache).

        Args:
            ohlcv_data: Dữ liệu OHLCV dạng list hoặc DataFrame.

        Returns:
            List [[ts_ms, o, h, l, c, v], ...].

        Raises:
            ValueError: Nếu input không hợp lệ.
        """
        if isinstance(ohlcv_data, list):
            return ohlcv_data

        if isinstance(ohlcv_data, pd.DataFrame):
            required = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required.issubset(set(ohlcv_data.columns)):
                raise ValueError(
                    f"DataFrame thiếu columns: {required - set(ohlcv_data.columns)}"
                )
            return ohlcv_data[["timestamp", "open", "high", "low", "close", "volume"]].values.tolist()

        raise ValueError(f"ohlcv_data phải là list hoặc DataFrame, got {type(ohlcv_data)}")

    @staticmethod
    def _resolve_range(
        candles:  list,
        start_ts: Optional[int],
        end_ts:   Optional[int],
    ) -> tuple[int, int]:
        """Xác định [start_idx, end_idx) để simulate.

        start_idx >= lookback để đảm bảo đủ warmup.

        Args:
            candles: Toàn bộ dữ liệu OHLCV.
            start_ts: Timestamp bắt đầu (ms). None = nến đầu tiên sau warmup.
            end_ts: Timestamp kết thúc (ms). None = nến cuối.

        Returns:
            Tuple (start_idx, end_idx).
        """
        n = len(candles)

        if start_ts is None:
            start_idx = 0
        else:
            start_idx = next(
                (i for i, c in enumerate(candles) if c[0] >= start_ts), n
            )

        if end_ts is None:
            end_idx = n
        else:
            end_idx = next(
                (i for i, c in enumerate(candles) if c[0] > end_ts), n
            )

        return start_idx, end_idx
