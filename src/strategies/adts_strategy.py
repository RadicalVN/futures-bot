"""
adts_strategy.py — Adaptive Dynamic Trend & Shield (ADTS) Strategy

Single-file strategy. Kế thừa BaseStrategy — không cần sửa bất kỳ file core nào.

Luồng xử lý:
  1. [Calibration]  Mỗi 24h: tính Base_ATR, Sideway_Threshold, Min_Slope từ D1
  2. [Filtering]    The Shield: ADX > 25, BBWidth > Threshold, |EMA20_Slope| > Min_Slope
  3. [Signaling]    Entry: Shield Passed + giá cắt EMA20 + slope đúng chiều
  4. [Execution]    SL/TP động theo ATR, TP1 chốt 50%, TP2 trailing, Emergency Exit

Indicators được tính qua src/data/indicators.py (dùng chung toàn platform).
Không import từ src/strategies/adts/ (package cũ đã bị xóa).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from src.data.indicators import (
    add_adx_to_df,
    add_atr_to_df,
    add_bbwidth_to_df,
    add_ema_slope_to_df,
    build_adts_snapshot,
    ADTSSnapshot,
)
from src.strategies.base_strategy import BaseStrategy, StrategySignal


# ── Inline dataclasses (thay thế adts/models.py) ─────────────────────────────

@dataclass
class _CalibrationResult:
    """Kết quả hiệu chỉnh hàng ngày từ dữ liệu D1.

    Attributes:
        calibrated_at: Thời điểm hiệu chỉnh.
        base_atr: ATR(14) trên D1.
        sideway_threshold: SMA(BBWidth, bbwidth_sma_period) * bbwidth_threshold_factor.
        min_slope: Base_ATR * min_slope_atr_factor / 5.
        d1_candles_used: Số nến D1 đã dùng.
    """
    calibrated_at:     datetime
    base_atr:          float
    sideway_threshold: float
    min_slope:         float
    d1_candles_used:   int

    @property
    def is_stale(self) -> bool:
        """True nếu calibration đã quá 26 giờ (buffer 2h)."""
        age_hours = (datetime.utcnow() - self.calibrated_at).total_seconds() / 3600
        return age_hours > 26.0


@dataclass
class _ShieldState:
    """Trạng thái bộ lọc sideway tại một thời điểm.

    Attributes:
        adx: Giá trị ADX hiện tại.
        bb_width: Giá trị BBWidth hiện tại.
        ema20_slope: Độ dốc EMA20 hiện tại.
        adx_ok: ADX vượt ngưỡng.
        bbwidth_ok: BBWidth vượt ngưỡng sideway.
        slope_ok: |EMA20_slope| vượt min_slope.
    """
    adx:        float
    bb_width:   float
    ema20_slope: float
    adx_ok:     bool
    bbwidth_ok: bool
    slope_ok:   bool

    @property
    def passed(self) -> bool:
        """True khi tất cả 3 điều kiện Shield đều thỏa."""
        return self.adx_ok and self.bbwidth_ok and self.slope_ok

    @property
    def summary(self) -> str:
        """Chuỗi mô tả trạng thái Shield để log."""
        flags = [
            f"ADX={self.adx:.1f}({'✓' if self.adx_ok else '✗'})",
            f"BBW={self.bb_width:.5f}({'✓' if self.bbwidth_ok else '✗'})",
            f"Slope={self.ema20_slope:+.6f}({'✓' if self.slope_ok else '✗'})",
        ]
        status = "PASS" if self.passed else "BLOCK"
        return f"Shield[{status}] {' | '.join(flags)}"


@dataclass
class _OrderState:
    """Trạng thái đầy đủ của một lệnh đang mở theo ADTS.

    Attributes:
        symbol: Symbol giao dịch.
        side: "long" hoặc "short".
        entry_price: Giá vào lệnh.
        amount_total: Tổng khối lượng ban đầu.
        amount_remaining: Khối lượng còn lại sau TP1.
        stop_loss: Giá stop loss hiện tại.
        take_profit_1: Giá TP1 (chốt 50%).
        take_profit_2_trail: Giá trailing stop hiện tại.
        atr_at_entry: ATR tại thời điểm vào lệnh.
        tp1_hit: Đã chốt 50% tại TP1 chưa.
        sl_moved_to_entry: Đã dời SL về entry sau TP1 chưa.
        opened_at: Thời điểm mở lệnh.
    """
    symbol:              str
    side:                str
    entry_price:         float
    amount_total:        float
    amount_remaining:    float
    stop_loss:           float
    take_profit_1:       float
    take_profit_2_trail: float
    atr_at_entry:        float
    tp1_hit:             bool = False
    sl_moved_to_entry:   bool = False
    opened_at:           datetime = field(default_factory=datetime.utcnow)

    def update_trailing_stop(
        self, current_price: float, atr: float, mult: float
    ) -> float:
        """Cập nhật trailing stop theo ATR — chỉ di chuyển theo hướng có lợi.

        Args:
            current_price: Giá hiện tại.
            atr: ATR hiện tại.
            mult: Hệ số ATR cho trailing stop.

        Returns:
            Giá trailing stop mới.
        """
        if self.side == "long":
            new_trail = current_price - mult * atr
            self.take_profit_2_trail = max(self.take_profit_2_trail, new_trail)
        else:
            new_trail = current_price + mult * atr
            self.take_profit_2_trail = min(self.take_profit_2_trail, new_trail)
        return self.take_profit_2_trail


# ── ADTSStrategy ──────────────────────────────────────────────────────────────

class ADTSStrategy(BaseStrategy):
    """Adaptive Dynamic Trend & Shield Strategy — Single-file plugin.

    Kế thừa BaseStrategy và triển khai đầy đủ Zero-Core-Edit contract:
    - STRATEGY_NAME = "adts"
    - get_required_lookback(): tự tính lookback dựa trên bbwidth_sma_period
    - prepare_metadata(): tính indicators cho ExitMonitorService
    - analyze(): logic giao dịch đầy đủ

    Không còn phụ thuộc vào src/strategies/adts/ package cũ.
    StrategyFactory tự phát hiện class này qua pkgutil.walk_packages.
    """

    STRATEGY_NAME: str = "adts"

    # ── Class-level contract ──────────────────────────────────────────────────

    @classmethod
    def get_required_lookback(cls, parameters: dict) -> int:
        """Tính số nến tối thiểu cần thiết để resample D1 và tính BBWidth SMA.

        ADTS cần lookback lớn vì:
        - Resample intraday → D1: cần nhiều nến 5m để có đủ nến D1
        - BBWidth SMA(200) trên D1: cần ít nhất 200 nến D1

        Args:
            parameters: Dict tham số từ Bot.parameters.

        Returns:
            Số nến tối thiểu (thường 2100 với bbwidth_sma_period=200).
        """
        bbwidth_sma = int(parameters.get("bbwidth_sma_period", 200))
        return bbwidth_sma * 10 + 100

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(self, config: dict) -> None:
        """Khởi tạo ADTSStrategy với config dict từ Bot.parameters.

        Đọc tất cả tham số qua self.get_param() — không dùng Pydantic ADTSConfig.
        Tương tự pattern của MaMacdStrategy và các strategy khác.

        Args:
            config: Dict tham số từ Bot.parameters trong DB.
        """
        super().__init__(config)

        # ── Indicator periods ─────────────────────────────────────────────────
        self._atr_period:        int   = int(self.get_param("atr_period", 14))
        self._adx_period:        int   = int(self.get_param("adx_period", 14))
        self._ema_period:        int   = int(self.get_param("ema_period", 20))
        self._ema200_period:     int   = int(self.get_param("ema200_period", 200))
        self._bb_period:         int   = int(self.get_param("bb_period", 20))
        self._bb_std:            float = float(self.get_param("bb_std", 2.0))
        self._bbwidth_sma_period: int  = int(self.get_param("bbwidth_sma_period", 200))

        # ── Shield thresholds ─────────────────────────────────────────────────
        self._adx_threshold:            float = float(self.get_param("adx_threshold", 20.0))
        self._bbwidth_threshold_factor: float = float(self.get_param("bbwidth_threshold_factor", 1.0))
        self._min_slope_atr_factor:     float = float(self.get_param("min_slope_atr_factor", 0.05))

        # ── Risk management ───────────────────────────────────────────────────
        self._sl_atr_mult:          float = float(self.get_param("sl_atr_mult", 1.5))
        self._hard_sl_pct:          float = float(self.get_param("hard_sl_pct", 0.03))
        self._tp1_rr:               float = float(self.get_param("tp1_rr", 1.2))
        self._tp1_close_pct:        float = float(self.get_param("tp1_close_pct", 0.5))
        self._tp2_trail_atr_mult:   float = float(self.get_param("tp2_trail_atr_mult", 2.0))

        # ── Emergency exit ────────────────────────────────────────────────────
        self._emergency_adx_threshold: float = float(self.get_param("emergency_adx_threshold", 20.0))
        self._emergency_close_pct:     float = float(self.get_param("emergency_close_pct", 0.5))

        # ── Calibration state ─────────────────────────────────────────────────
        self._calibration: Optional[_CalibrationResult] = None
        self._calibration_lock = asyncio.Lock()

        # ── Per-symbol order state ────────────────────────────────────────────
        # Key: symbol (normalized), Value: _OrderState
        self._order_states: dict[str, _OrderState] = {}

        logger.info(
            f"[ADTS] Khởi tạo | "
            f"ADX_thr={self._adx_threshold} | "
            f"SL={self._sl_atr_mult}×ATR | "
            f"TP1=R:R1:{self._tp1_rr} | "
            f"TP2=Trail{self._tp2_trail_atr_mult}×ATR"
        )

    # ── prepare_metadata (BaseStrategy contract) ──────────────────────────────

    async def prepare_metadata(self, df: pd.DataFrame) -> dict:
        """Tính ADX, BBWidth, EMA20 slope cho ExitMonitorService.

        Được gọi bởi ExitMonitorService để kiểm tra exit condition
        mà không cần biết strategy cụ thể là gì.

        Args:
            df: DataFrame OHLCV với columns [timestamp, open, high, low, close, volume].

        Returns:
            Dict metadata chứa các giá trị indicator cần thiết cho exit check.
            Trả về {} nếu không đủ dữ liệu hoặc có lỗi.
        """
        try:
            snap = build_adts_snapshot(
                df,
                atr_period=self._atr_period,
                adx_period=self._adx_period,
                ema_period=self._ema_period,
                ema200_period=self._ema200_period,
                bb_period=self._bb_period,
                bb_std=self._bb_std,
            )
            if snap is None:
                return {}
            calibration = self._calibration
            return {
                "adx":                     snap.adx,
                "bb_width":                snap.bb_width,
                "ema20_slope":             snap.ema20_slope,
                "close":                   snap.close,
                "high":                    snap.high,
                "low":                     snap.low,
                "atr":                     snap.atr,
                "sideway_threshold":       calibration.sideway_threshold if calibration else 0.0,
                "emergency_adx_threshold": self._emergency_adx_threshold,
            }
        except Exception:
            return {}

    # ── analyze (BaseStrategy contract) ──────────────────────────────────────

    async def analyze(
        self,
        symbol:            str,
        ohlcv_data:        list,
        current_positions: list,
    ) -> StrategySignal:
        """Phân tích OHLCV và trả về StrategySignal.

        Luồng: Calibration → Filtering (Shield) → Exit checks → Entry Signal.

        Args:
            symbol: Symbol giao dịch (vd: "BTC/USDT").
            ohlcv_data: List [[timestamp_ms, open, high, low, close, volume], ...].
            current_positions: List vị thế đang mở từ exchange.

        Returns:
            StrategySignal với signal, price, reason, metadata.
        """
        if len(ohlcv_data) < 50:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason=f"Không đủ dữ liệu: có {len(ohlcv_data)} nến, cần ≥50",
            )

        df = self._to_dataframe(ohlcv_data)

        # Bước 1: Calibration (D1) — chạy nếu chưa có hoặc đã stale
        calibration = await self._ensure_calibration(ohlcv_data, symbol)
        if calibration is None:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Calibration chưa sẵn sàng — thiếu dữ liệu D1",
                metadata={"shield_passed": False, "calibration_ready": False},
            )

        # Bước 2: Tính indicator intraday
        snap = build_adts_snapshot(
            df,
            atr_period=self._atr_period,
            adx_period=self._adx_period,
            ema_period=self._ema_period,
            ema200_period=self._ema200_period,
            bb_period=self._bb_period,
            bb_std=self._bb_std,
        )
        if snap is None:
            return StrategySignal(
                signal="none", symbol=symbol, price=0,
                reason="Không đủ dữ liệu để tính indicator",
            )

        # Bước 3: The Shield (Sideway Filter)
        shield = self._evaluate_shield(snap, calibration)
        logger.debug(f"[ADTS][{symbol}] {shield.summary}")

        # Bước 4: Kiểm tra vị thế hiện tại
        pos_side    = self._get_position_side(symbol, current_positions)
        order_state = self._order_states.get(symbol)

        # Bước 5: Exit checks (ưu tiên trước entry)
        if pos_side is not None and order_state is not None:
            exit_signal = self._check_exits(symbol, snap, order_state, calibration, shield)
            if exit_signal is not None:
                if exit_signal.metadata and exit_signal.metadata.get("full_close", False):
                    self._order_states.pop(symbol, None)
                return exit_signal

        # Bước 6: Entry Signal
        if pos_side is None:
            entry_signal = self._check_entry(symbol, snap, shield, calibration)
            if entry_signal is not None:
                return entry_signal

        # Không có tín hiệu
        reason_parts = [shield.summary]
        if pos_side:
            reason_parts.append(f"Đang giữ {pos_side.upper()}")
        return StrategySignal(
            signal="none",
            symbol=symbol,
            price=snap.close,
            reason=" | ".join(reason_parts),
            metadata=self._build_metadata(snap, calibration, shield),
        )

    # ── Calibration helpers ───────────────────────────────────────────────────

    async def _ensure_calibration(
        self, intraday_ohlcv: list, symbol: str
    ) -> Optional[_CalibrationResult]:
        """Đảm bảo calibration còn hiệu lực, chạy lại nếu stale.

        Args:
            intraday_ohlcv: Dữ liệu OHLCV intraday để resample sang D1.
            symbol: Tên symbol (chỉ dùng cho logging).

        Returns:
            _CalibrationResult hoặc None nếu không đủ dữ liệu.
        """
        async with self._calibration_lock:
            if self._calibration is not None and not self._calibration.is_stale:
                return self._calibration

            logger.info(f"[ADTS][{symbol}] Chạy Daily Calibration...")
            d1_ohlcv = self._resample_to_d1(intraday_ohlcv)
            if not d1_ohlcv:
                logger.warning(f"[ADTS][{symbol}] Không thể resample sang D1")
                return self._calibration

            result = self._run_calibration(d1_ohlcv, symbol)
            if result is not None:
                self._calibration = result
            return self._calibration

    def _resample_to_d1(self, ohlcv: list) -> list:
        """Resample dữ liệu intraday sang D1 bằng pandas.

        Args:
            ohlcv: List [[ts_ms, o, h, l, c, v], ...] intraday.

        Returns:
            List [[ts_ms, o, h, l, c, v], ...] dạng D1, hoặc [] nếu lỗi.
        """
        try:
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp").astype(float)

            d1 = df.resample("1D").agg({
                "open": "first", "high": "max",
                "low": "min", "close": "last", "volume": "sum",
            }).dropna()

            if len(d1) < 10:
                return []

            return [
                [int(ts.timestamp() * 1000),
                 float(row["open"]), float(row["high"]),
                 float(row["low"]),  float(row["close"]), float(row["volume"])]
                for ts, row in d1.iterrows()
            ]
        except Exception as exc:
            logger.error(f"[ADTS] Lỗi resample D1: {exc}")
            return []

    def _run_calibration(
        self, d1_ohlcv: list, symbol: str = ""
    ) -> Optional[_CalibrationResult]:
        """Tính Base_ATR, Sideway_Threshold, Min_Slope từ dữ liệu D1.

        Args:
            d1_ohlcv: Dữ liệu OHLCV D1 [[ts_ms, o, h, l, c, v], ...].
            symbol: Tên symbol (chỉ dùng cho logging).

        Returns:
            _CalibrationResult hoặc None nếu không đủ dữ liệu.
        """
        tag = f"[Calibration][{symbol}]" if symbol else "[Calibration]"
        min_required = self._bbwidth_sma_period + self._atr_period + 10
        if len(d1_ohlcv) < min_required:
            logger.warning(
                f"{tag} Không đủ dữ liệu D1: có {len(d1_ohlcv)}, cần ≥{min_required}"
            )
            return None

        try:
            df = pd.DataFrame(
                d1_ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.astype({
                "open": float, "high": float, "low": float,
                "close": float, "volume": float,
            }).set_index("timestamp")

            df = add_atr_to_df(df, self._atr_period)
            df = add_bbwidth_to_df(df, self._bb_period, self._bb_std)

            base_atr = float(df["atr"].iloc[-1])
            if np.isnan(base_atr) or base_atr <= 0:
                logger.error(f"{tag} Base_ATR không hợp lệ: {base_atr}")
                return None

            bbwidth_sma = df["bb_width"].rolling(self._bbwidth_sma_period).mean()
            bbwidth_sma_val = float(bbwidth_sma.iloc[-1])
            if np.isnan(bbwidth_sma_val) or bbwidth_sma_val <= 0:
                logger.error(f"{tag} BBWidth SMA không hợp lệ: {bbwidth_sma_val}")
                return None

            sideway_threshold = bbwidth_sma_val * self._bbwidth_threshold_factor
            min_slope = (base_atr * self._min_slope_atr_factor) / 5.0

            result = _CalibrationResult(
                calibrated_at=datetime.utcnow(),
                base_atr=base_atr,
                sideway_threshold=sideway_threshold,
                min_slope=min_slope,
                d1_candles_used=len(d1_ohlcv),
            )
            logger.info(
                f"{tag} ✅ Hiệu chỉnh hoàn tất | "
                f"Base_ATR={base_atr:.4f} | "
                f"Sideway_Thr={sideway_threshold:.6f} | "
                f"Min_Slope={min_slope:.8f}"
            )
            return result
        except Exception as exc:
            logger.error(f"{tag} Lỗi calibration: {type(exc).__name__}: {exc}")
            return None

    # ── Shield ────────────────────────────────────────────────────────────────

    def _evaluate_shield(
        self, snap: ADTSSnapshot, calibration: _CalibrationResult
    ) -> _ShieldState:
        """Đánh giá 3 điều kiện của The Shield.

        Args:
            snap: ADTSSnapshot tại nến cuối.
            calibration: Kết quả calibration hiện tại.

        Returns:
            _ShieldState với trạng thái từng điều kiện.
        """
        adx_ok     = snap.adx > self._adx_threshold
        bbwidth_ok = snap.bb_width > calibration.sideway_threshold
        slope_ok   = abs(snap.ema20_slope) > calibration.min_slope
        return _ShieldState(
            adx=snap.adx,
            bb_width=snap.bb_width,
            ema20_slope=snap.ema20_slope,
            adx_ok=adx_ok,
            bbwidth_ok=bbwidth_ok,
            slope_ok=slope_ok,
        )

    # ── Entry Signal ──────────────────────────────────────────────────────────

    def _check_entry(
        self,
        symbol:      str,
        snap:        ADTSSnapshot,
        shield:      _ShieldState,
        calibration: _CalibrationResult,
    ) -> Optional[StrategySignal]:
        """Kiểm tra điều kiện vào lệnh.

        Buy:  Shield Passed + close > EMA20 + EMA20_Slope > 0 + close > EMA200
        Sell: Shield Passed + close < EMA20 + EMA20_Slope < 0 + close < EMA200

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            shield: Trạng thái Shield hiện tại.
            calibration: Kết quả calibration hiện tại.

        Returns:
            StrategySignal entry hoặc None nếu không thỏa điều kiện.
        """
        if not shield.passed:
            return None

        above_ema200 = snap.close > snap.ema200
        below_ema200 = snap.close < snap.ema200

        buy_condition = (
            snap.close > snap.ema20
            and snap.ema20_slope > 0
            and above_ema200
        )
        sell_condition = (
            snap.close < snap.ema20
            and snap.ema20_slope < 0
            and below_ema200
        )

        if not buy_condition and not sell_condition:
            self._log_trend_filter_block(symbol, snap, shield, above_ema200, below_ema200)
            return None

        side        = "long" if buy_condition else "short"
        entry_price = snap.close

        sl_distance, sl_source = self._calc_sl_distance(entry_price, snap.atr)
        tp1_distance       = sl_distance * self._tp1_rr
        tp2_trail_distance = self._tp2_trail_atr_mult * snap.atr

        if side == "long":
            stop_loss     = entry_price - sl_distance
            take_profit_1 = entry_price + tp1_distance
            tp2_initial   = entry_price - tp2_trail_distance
        else:
            stop_loss     = entry_price + sl_distance
            take_profit_1 = entry_price - tp1_distance
            tp2_initial   = entry_price + tp2_trail_distance

        reason = (
            f"ADTS {side.upper()} | Shield PASS | "
            f"ADX={snap.adx:.1f} | BBW={snap.bb_width:.5f} | "
            f"Slope={snap.ema20_slope:+.6f} | "
            f"EMA200={'above' if above_ema200 else 'below'} | "
            f"SL={stop_loss:.4f}({sl_source}) | TP1={take_profit_1:.4f}"
        )
        logger.info(f"[ADTS][{symbol}] {reason}")

        metadata = self._build_metadata(snap, calibration, shield)
        metadata.update({
            "entry_price":       round(entry_price, 6),
            "stop_loss":         round(stop_loss, 6),
            "take_profit_1":     round(take_profit_1, 6),
            "tp2_initial_trail": round(tp2_initial, 6),
            "sl_distance":       round(sl_distance, 6),
            "sl_source":         sl_source,
            "atr_at_entry":      round(snap.atr, 6),
            "ema200":            round(snap.ema200, 6),
            "above_ema200":      above_ema200,
        })

        return StrategySignal(
            signal=side,
            symbol=symbol,
            price=entry_price,
            reason=reason,
            confidence=self._calc_confidence(snap),
            metadata=metadata,
        )

    def _log_trend_filter_block(
        self,
        symbol:       str,
        snap:         ADTSSnapshot,
        shield:       _ShieldState,
        above_ema200: bool,
        below_ema200: bool,
    ) -> None:
        """Log lý do bị chặn bởi Trend Filter (EMA200).

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            shield: Trạng thái Shield hiện tại.
            above_ema200: Giá đang trên EMA200.
            below_ema200: Giá đang dưới EMA200.
        """
        if not shield.passed:
            return
        if snap.close > snap.ema20 and snap.ema20_slope > 0 and not above_ema200:
            logger.debug(
                f"[ADTS][{symbol}] Trend Filter BLOCK LONG: "
                f"close={snap.close:.4f} < EMA200={snap.ema200:.4f}"
            )
        elif snap.close < snap.ema20 and snap.ema20_slope < 0 and not below_ema200:
            logger.debug(
                f"[ADTS][{symbol}] Trend Filter BLOCK SHORT: "
                f"close={snap.close:.4f} > EMA200={snap.ema200:.4f}"
            )

    # ── Exit Checks ───────────────────────────────────────────────────────────

    def _check_exits(
        self,
        symbol:      str,
        snap:        ADTSSnapshot,
        order_state: _OrderState,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
    ) -> Optional[StrategySignal]:
        """Kiểm tra tất cả điều kiện thoát lệnh theo thứ tự ưu tiên.

        Thứ tự: Emergency Exit → Stop Loss → TP1 → TP2 Trailing Stop.

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            order_state: Trạng thái lệnh đang mở.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            StrategySignal exit hoặc None nếu chưa cần đóng.
        """
        side  = order_state.side
        close = snap.close
        high  = snap.high
        low   = snap.low

        # 1. Emergency Exit
        emg_signal = self._check_emergency_exit(
            symbol, snap, order_state, calibration, shield
        )
        if emg_signal is not None:
            return emg_signal

        # 2. Stop Loss
        sl = order_state.stop_loss
        if side == "long" and low <= sl:
            reason = (
                f"🛑 SL LONG: low={low:.4f} ≤ SL={sl:.4f} "
                f"({'Entry SL' if order_state.sl_moved_to_entry else 'ATR SL'})"
            )
            logger.info(f"[ADTS][{symbol}] {reason}")
            return self._make_exit_signal(
                symbol=symbol, side=side, price=min(sl, close),
                reason=reason, partial=False,
                snap=snap, calibration=calibration, shield=shield, full_close=True,
            )

        if side == "short" and high >= sl:
            reason = (
                f"🛑 SL SHORT: high={high:.4f} ≥ SL={sl:.4f} "
                f"({'Entry SL' if order_state.sl_moved_to_entry else 'ATR SL'})"
            )
            logger.info(f"[ADTS][{symbol}] {reason}")
            return self._make_exit_signal(
                symbol=symbol, side=side, price=max(sl, close),
                reason=reason, partial=False,
                snap=snap, calibration=calibration, shield=shield, full_close=True,
            )

        # 3. TP1 (chốt 50% nếu chưa hit)
        tp1_signal = self._check_tp1(symbol, snap, order_state, calibration, shield)
        if tp1_signal is not None:
            return tp1_signal

        # 4. TP2 Trailing Stop
        return self._check_tp2_trail(symbol, snap, order_state, calibration, shield)

    def _check_emergency_exit(
        self,
        symbol:      str,
        snap:        ADTSSnapshot,
        order_state: _OrderState,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
    ) -> Optional[StrategySignal]:
        """Kiểm tra điều kiện Emergency Exit.

        Kích hoạt khi ADX < emergency_adx_threshold HOẶC BBWidth < sideway_threshold.

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            order_state: Trạng thái lệnh đang mở.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            StrategySignal emergency exit hoặc None.
        """
        is_emergency = False
        emg_reason   = ""

        if snap.adx < self._emergency_adx_threshold:
            is_emergency = True
            emg_reason = (
                f"🚨 Emergency Exit: ADX={snap.adx:.1f} < "
                f"{self._emergency_adx_threshold} (xu hướng suy yếu)"
            )
        elif snap.bb_width < calibration.sideway_threshold:
            is_emergency = True
            emg_reason = (
                f"🚨 Emergency Exit: BBWidth={snap.bb_width:.5f} < "
                f"Threshold={calibration.sideway_threshold:.5f} (thị trường nén lại)"
            )

        if not is_emergency:
            return None

        logger.warning(f"[ADTS][{symbol}] {emg_reason}")
        order_state.update_trailing_stop(
            snap.close, snap.atr, self._tp2_trail_atr_mult
        )
        return self._make_exit_signal(
            symbol=symbol, side=order_state.side, price=snap.close,
            reason=emg_reason, partial=True,
            partial_pct=self._emergency_close_pct,
            snap=snap, calibration=calibration, shield=shield, full_close=False,
        )

    def _check_tp1(
        self,
        symbol:      str,
        snap:        ADTSSnapshot,
        order_state: _OrderState,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
    ) -> Optional[StrategySignal]:
        """Kiểm tra điều kiện TP1 (chốt 50%).

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            order_state: Trạng thái lệnh đang mở.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            StrategySignal TP1 partial close hoặc None.
        """
        if order_state.tp1_hit:
            return None

        side = order_state.side
        tp1  = order_state.take_profit_1
        tp1_hit = (
            (side == "long"  and snap.high >= tp1) or
            (side == "short" and snap.low  <= tp1)
        )
        if not tp1_hit:
            return None

        reason = (
            f"🎯 TP1 {side.upper()}: "
            f"{'high' if side == 'long' else 'low'}="
            f"{snap.high if side == 'long' else snap.low:.4f} "
            f"{'≥' if side == 'long' else '≤'} TP1={tp1:.4f} "
            f"(chốt {self._tp1_close_pct*100:.0f}%)"
        )
        logger.info(f"[ADTS][{symbol}] {reason}")

        # Cập nhật order state
        order_state.tp1_hit           = True
        order_state.sl_moved_to_entry = True
        order_state.stop_loss         = order_state.entry_price
        order_state.take_profit_2_trail = tp1
        order_state.amount_remaining  = (
            order_state.amount_total * (1.0 - self._tp1_close_pct)
        )
        logger.info(
            f"[ADTS][{symbol}] SL dời về Entry={order_state.entry_price:.4f} | "
            f"Còn lại {order_state.amount_remaining:.4f} contracts"
        )

        return self._make_exit_signal(
            symbol=symbol, side=side, price=tp1,
            reason=reason, partial=True,
            partial_pct=self._tp1_close_pct,
            snap=snap, calibration=calibration, shield=shield, full_close=False,
        )

    def _check_tp2_trail(
        self,
        symbol:      str,
        snap:        ADTSSnapshot,
        order_state: _OrderState,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
    ) -> Optional[StrategySignal]:
        """Kiểm tra điều kiện TP2 Trailing Stop.

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            order_state: Trạng thái lệnh đang mở.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            StrategySignal TP2 full close hoặc None.
        """
        if not order_state.tp1_hit:
            return None

        order_state.update_trailing_stop(snap.close, snap.atr, self._tp2_trail_atr_mult)
        trail = order_state.take_profit_2_trail
        side  = order_state.side

        trail_hit = (
            (side == "long"  and snap.low  <= trail) or
            (side == "short" and snap.high >= trail)
        )
        if not trail_hit:
            return None

        reason = (
            f"🏁 TP2 Trailing {side.upper()}: "
            f"{'low' if side == 'long' else 'high'}="
            f"{snap.low if side == 'long' else snap.high:.4f} "
            f"{'≤' if side == 'long' else '≥'} Trail={trail:.4f} "
            f"({self._tp2_trail_atr_mult}×ATR)"
        )
        logger.info(f"[ADTS][{symbol}] {reason}")
        return self._make_exit_signal(
            symbol=symbol, side=side, price=trail,
            reason=reason, partial=False,
            snap=snap, calibration=calibration, shield=shield, full_close=True,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_exit_signal(
        self,
        symbol:      str,
        side:        str,
        price:       float,
        reason:      str,
        partial:     bool,
        snap:        ADTSSnapshot,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
        partial_pct: float = 0.5,
        full_close:  bool  = True,
    ) -> StrategySignal:
        """Tạo StrategySignal thoát lệnh.

        Args:
            symbol: Symbol giao dịch.
            side: "long" hoặc "short".
            price: Giá đóng lệnh.
            reason: Lý do đóng lệnh.
            partial: True nếu chỉ đóng một phần.
            snap: ADTSSnapshot tại nến cuối.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.
            partial_pct: Tỷ lệ đóng nếu partial=True.
            full_close: True nếu đóng toàn bộ vị thế.

        Returns:
            StrategySignal với signal="close_long" hoặc "close_short".
        """
        meta = self._build_metadata(snap, calibration, shield)
        meta.update({
            "partial_close": partial,
            "partial_pct":   partial_pct if partial else 1.0,
            "full_close":    full_close,
        })
        return StrategySignal(
            signal=f"close_{side}",
            symbol=symbol,
            price=price,
            reason=reason,
            metadata=meta,
        )

    def _get_position_side(self, symbol: str, positions: list) -> Optional[str]:
        """Lấy side của vị thế đang mở cho symbol này.

        Args:
            symbol: Symbol giao dịch (vd: "BTC/USDT").
            positions: List vị thế từ exchange.

        Returns:
            "long" | "short" hoặc None nếu không có vị thế.
        """
        sym_clean = symbol.replace("/", "").replace(":USDT", "")
        for pos in positions:
            pos_sym = pos.get("symbol", "").replace("/", "").replace(":USDT", "")
            if pos_sym == sym_clean:
                size = float(pos.get("contracts", pos.get("size", 0)) or 0)
                if size > 0:
                    return pos.get("side", "long")
        return None

    def _calc_sl_distance(
        self, entry_price: float, atr: float
    ) -> tuple[float, str]:
        """Tính khoảng cách Stop Loss — lấy mức nào gần entry hơn.

        Args:
            entry_price: Giá vào lệnh.
            atr: ATR hiện tại.

        Returns:
            Tuple (sl_distance, sl_source) — sl_source là "ATR" hoặc "Hard".
        """
        atr_sl_distance  = self._sl_atr_mult * atr
        hard_sl_distance = entry_price * self._hard_sl_pct
        if atr_sl_distance <= hard_sl_distance:
            return atr_sl_distance, "ATR"
        return hard_sl_distance, "Hard"

    def _calc_confidence(self, snap: ADTSSnapshot) -> float:
        """Tính confidence score 0.0 → 1.0 dựa trên sức mạnh ADX.

        Args:
            snap: ADTSSnapshot tại nến cuối.

        Returns:
            Confidence score từ 0.5 đến 1.0.
        """
        adx_score = min((snap.adx - self._adx_threshold) / 25.0, 1.0)
        adx_score = max(adx_score, 0.0)
        return round(0.5 + adx_score * 0.5, 2)

    def _build_metadata(
        self,
        snap:        ADTSSnapshot,
        calibration: _CalibrationResult,
        shield:      _ShieldState,
    ) -> dict:
        """Tổng hợp metadata để hiển thị trên dashboard và lưu DB.

        Args:
            snap: ADTSSnapshot tại nến cuối.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            Dict metadata đầy đủ.
        """
        return {
            "close":              round(snap.close, 6),
            "high":               round(snap.high, 6),
            "low":                round(snap.low, 6),
            "atr":                round(snap.atr, 6),
            "adx":                round(snap.adx, 2),
            "bb_width":           round(snap.bb_width, 6),
            "ema20":              round(snap.ema20, 6),
            "ema20_slope":        round(snap.ema20_slope, 8),
            "ema200":             round(snap.ema200, 6),
            "above_ema200":       snap.close > snap.ema200,
            "base_atr_d1":        round(calibration.base_atr, 6),
            "sideway_threshold":  round(calibration.sideway_threshold, 6),
            "min_slope":          round(calibration.min_slope, 8),
            "calibrated_at":      calibration.calibrated_at.isoformat(),
            "shield_passed":      shield.passed,
            "adx_ok":             shield.adx_ok,
            "bbwidth_ok":         shield.bbwidth_ok,
            "slope_ok":           shield.slope_ok,
        }

    @staticmethod
    def _to_dataframe(ohlcv_data: list) -> pd.DataFrame:
        """Chuyển list OHLCV sang DataFrame với kiểu float.

        Args:
            ohlcv_data: List [[ts_ms, o, h, l, c, v], ...].

        Returns:
            DataFrame với columns [timestamp, open, high, low, close, volume].
        """
        df = pd.DataFrame(
            ohlcv_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        return df.astype({
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        })

    # ── Public order state management ─────────────────────────────────────────

    def register_order_state(
        self,
        symbol:           str,
        side:             str,
        entry_price:      float,
        amount:           float,
        stop_loss:        float,
        take_profit_1:    float,
        tp2_initial_trail: float,
        atr:              float,
    ) -> None:
        """Đăng ký trạng thái lệnh mới sau khi entry được thực thi.

        Được gọi từ bên ngoài (bot_engine hoặc order_manager) sau khi lệnh khớp.

        Args:
            symbol: Symbol giao dịch.
            side: "long" hoặc "short".
            entry_price: Giá vào lệnh.
            amount: Khối lượng lệnh.
            stop_loss: Giá stop loss ban đầu.
            take_profit_1: Giá TP1.
            tp2_initial_trail: Giá trailing stop ban đầu.
            atr: ATR tại thời điểm vào lệnh.
        """
        self._order_states[symbol] = _OrderState(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            amount_total=amount,
            amount_remaining=amount,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2_trail=tp2_initial_trail,
            atr_at_entry=atr,
        )
        logger.info(
            f"[ADTS][{symbol}] OrderState đăng ký: "
            f"{side.upper()} entry={entry_price:.4f} "
            f"SL={stop_loss:.4f} TP1={take_profit_1:.4f} "
            f"Trail_init={tp2_initial_trail:.4f}"
        )

    def clear_order_state(self, symbol: str) -> None:
        """Xóa order state khi lệnh đã đóng hoàn toàn.

        Args:
            symbol: Symbol giao dịch cần xóa state.
        """
        self._order_states.pop(symbol, None)
        logger.debug(f"[ADTS][{symbol}] OrderState đã xóa")
