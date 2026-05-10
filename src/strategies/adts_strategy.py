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

State Persistence (fix ADTS-001):
  _OrderState được persist vào Trade.signal_metadata["adts_order_state"] sau mỗi lần
  thay đổi (entry, TP1 hit, trailing update). Khi bot restart, restore_order_states_from_db()
  reconstruct _order_states từ các Trade có status='filled' và closed_at IS NULL.

Calibration Fallback (fix ADTS-002):
  _ensure_calibration() luôn trả về _CalibrationResult (không bao giờ None).
  3 tầng fallback:
    Tầng 1 — Fresh: đủ dữ liệu D1, tính toán thành công.
    Tầng 2 — Stale: dùng calibration cũ (dù > 26h), log WARNING.
    Tầng 3 — Hardcoded: không có gì cả, dùng giá trị conservative, log CRITICAL.
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
        d1_candles_used: Số nến D1 đã dùng. 0 = hardcoded default (không có dữ liệu D1).
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

    @property
    def is_hardcoded_default(self) -> bool:
        """True nếu đây là giá trị mặc định hardcoded, không phải từ dữ liệu D1 thực.

        Khi True: Shield chỉ còn ADX filter hoạt động — BBWidth và Slope bị vô hiệu hóa
        vì sideway_threshold=0.0 và min_slope=1e-9 luôn được thỏa mãn.
        """
        return self.d1_candles_used == 0

    @property
    def age_hours(self) -> float:
        """Tuổi của calibration tính bằng giờ."""
        return (datetime.utcnow() - self.calibrated_at).total_seconds() / 3600


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
        amount_remaining: Khối lượng còn lại sau TP1 hoặc Emergency Giai đoạn 1.
        stop_loss: Giá stop loss hiện tại.
        take_profit_1: Giá TP1 (chốt 50%).
        take_profit_2_trail: Giá trailing stop hiện tại.
        atr_at_entry: ATR tại thời điểm vào lệnh.
        tp1_hit: Đã chốt 50% tại TP1 chưa.
        sl_moved_to_entry: Đã dời SL về entry sau TP1 chưa.
        emergency_triggered: Đã thực hiện Emergency Exit Giai đoạn 1 chưa.
            True = đã đóng emergency_close_pct, đang chờ xem nến tiếp theo.
            Nếu Shield vẫn vi phạm → Giai đoạn 2 đóng 100% còn lại.
            Nếu Shield phục hồi → reset về False, tiếp tục giữ vị thế.
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
    emergency_triggered: bool = False
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

    def to_dict(self) -> dict:
        """Serialize _OrderState sang dict để persist vào Trade.signal_metadata.

        Returns:
            Dict JSON-serializable chứa toàn bộ trạng thái lệnh.
        """
        return {
            "symbol":               self.symbol,
            "side":                 self.side,
            "entry_price":          self.entry_price,
            "amount_total":         self.amount_total,
            "amount_remaining":     self.amount_remaining,
            "stop_loss":            self.stop_loss,
            "take_profit_1":        self.take_profit_1,
            "take_profit_2_trail":  self.take_profit_2_trail,
            "atr_at_entry":         self.atr_at_entry,
            "tp1_hit":              self.tp1_hit,
            "sl_moved_to_entry":    self.sl_moved_to_entry,
            "emergency_triggered":  self.emergency_triggered,
            "opened_at":            self.opened_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "_OrderState":
        """Deserialize dict từ Trade.signal_metadata về _OrderState.

        Args:
            data: Dict đã được lưu bởi to_dict().

        Returns:
            _OrderState instance được reconstruct.
        """
        opened_at = datetime.utcnow()
        raw_opened = data.get("opened_at")
        if raw_opened:
            try:
                opened_at = datetime.fromisoformat(raw_opened)
            except (ValueError, TypeError):
                pass

        return cls(
            symbol=data["symbol"],
            side=data["side"],
            entry_price=float(data["entry_price"]),
            amount_total=float(data["amount_total"]),
            amount_remaining=float(data["amount_remaining"]),
            stop_loss=float(data["stop_loss"]),
            take_profit_1=float(data["take_profit_1"]),
            take_profit_2_trail=float(data["take_profit_2_trail"]),
            atr_at_entry=float(data["atr_at_entry"]),
            tp1_hit=bool(data.get("tp1_hit", False)),
            sl_moved_to_entry=bool(data.get("sl_moved_to_entry", False)),
            emergency_triggered=bool(data.get("emergency_triggered", False)),
            opened_at=opened_at,
        )


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

    PARAMETERS_SCHEMA: dict = {
        "type": "object",
        "properties": {
            "timeframe": {
                "type": "string",
                "title": "Timeframe",
                "description": "Khung thoi gian nen intraday",
                "default": "5m",
                "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "4h"],
                "ui:widget": "select",
            },
            "atr_period": {
                "type": "integer",
                "title": "ATR Period",
                "description": "Chu ky ATR cho D1 calibration va SL/TP dong",
                "default": 14,
                "minimum": 2,
                "maximum": 50,
                "ui:widget": "number",
            },
            "adx_period": {
                "type": "integer",
                "title": "ADX Period",
                "description": "Chu ky ADX cho The Shield",
                "default": 14,
                "minimum": 2,
                "maximum": 50,
                "ui:widget": "number",
            },
            "ema_period": {
                "type": "integer",
                "title": "EMA Period (Entry Signal)",
                "description": "Chu ky EMA dung cho tin hieu entry (gia cat EMA)",
                "default": 20,
                "minimum": 2,
                "maximum": 200,
                "ui:widget": "number",
            },
            "ema200_period": {
                "type": "integer",
                "title": "EMA200 Period (Trend Filter)",
                "description": "Chu ky EMA dai han — Long chi khi gia tren, Short chi khi gia duoi",
                "default": 200,
                "minimum": 50,
                "maximum": 500,
                "ui:widget": "number",
            },
            "bb_period": {
                "type": "integer",
                "title": "Bollinger Bands Period",
                "description": "Chu ky Bollinger Bands de tinh BBWidth",
                "default": 20,
                "minimum": 5,
                "maximum": 100,
                "ui:widget": "number",
            },
            "bb_std": {
                "type": "number",
                "title": "BB Std Multiplier",
                "description": "He so do lech chuan Bollinger Bands",
                "default": 2.0,
                "minimum": 0.5,
                "maximum": 5.0,
                "ui:widget": "number",
            },
            "bbwidth_sma_period": {
                "type": "integer",
                "title": "BBWidth SMA Period",
                "description": "Chu ky SMA cua BBWidth tren D1 de tinh Sideway Threshold",
                "default": 200,
                "minimum": 10,
                "maximum": 500,
                "ui:widget": "number",
            },
            "adx_threshold": {
                "type": "number",
                "title": "ADX Threshold (Shield)",
                "description": "ADX phai vuot nguong nay de Shield PASS",
                "default": 20.0,
                "minimum": 5.0,
                "maximum": 60.0,
                "ui:widget": "number",
            },
            "bbwidth_threshold_factor": {
                "type": "number",
                "title": "BBWidth Threshold Factor",
                "description": "He so nhan SMA(BBWidth) de tinh Sideway Threshold (1.0 = stricter)",
                "default": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "ui:widget": "number",
            },
            "min_slope_atr_factor": {
                "type": "number",
                "title": "Min Slope ATR Factor",
                "description": "He so ATR de tinh Min_Slope = Base_ATR * factor / 5",
                "default": 0.05,
                "minimum": 0.01,
                "maximum": 0.5,
                "ui:widget": "number",
            },
            "sl_atr_mult": {
                "type": "number",
                "title": "SL ATR Multiplier",
                "description": "He so ATR cho Stop Loss dong (SL = entry +/- sl_atr_mult x ATR)",
                "default": 1.5,
                "minimum": 0.5,
                "maximum": 5.0,
                "ui:widget": "number",
            },
            "hard_sl_pct": {
                "type": "number",
                "title": "Hard Stop Loss (%)",
                "description": "Hard SL toi da theo % gia entry — SL thuc = min(ATR SL, Hard SL)",
                "default": 0.03,
                "minimum": 0.005,
                "maximum": 0.2,
                "ui:widget": "number",
            },
            "tp1_rr": {
                "type": "number",
                "title": "TP1 Risk:Reward",
                "description": "Ty le R:R cho TP1 (chot 50% vi the)",
                "default": 1.2,
                "minimum": 0.5,
                "maximum": 5.0,
                "ui:widget": "number",
            },
            "tp1_close_pct": {
                "type": "number",
                "title": "TP1 Close Percentage",
                "description": "Ty le % vi the chot tai TP1",
                "default": 0.5,
                "minimum": 0.1,
                "maximum": 1.0,
                "ui:widget": "number",
            },
            "tp2_trail_atr_mult": {
                "type": "number",
                "title": "TP2 Trailing ATR Multiplier",
                "description": "He so ATR cho Trailing Stop TP2 (phan con lai sau TP1)",
                "default": 2.0,
                "minimum": 0.5,
                "maximum": 10.0,
                "ui:widget": "number",
            },
            "emergency_adx_threshold": {
                "type": "number",
                "title": "Emergency Exit ADX Threshold",
                "description": "ADX cat xuong duoi nguong nay → Emergency Exit (dong 50%)",
                "default": 20.0,
                "minimum": 5.0,
                "maximum": 50.0,
                "ui:widget": "number",
            },
            "emergency_close_pct": {
                "type": "number",
                "title": "Emergency Close Percentage",
                "description": "Ty le % vi the dong khi Emergency Exit",
                "default": 0.5,
                "minimum": 0.1,
                "maximum": 1.0,
                "ui:widget": "number",
            },
            "leverage": {
                "type": "integer",
                "title": "Leverage",
                "description": "Don bay giao dich",
                "default": 5,
                "minimum": 1,
                "maximum": 125,
                "ui:widget": "number",
            },
            "position_size_pct": {
                "type": "number",
                "title": "Position Size (%)",
                "description": "Ty le von moi lenh (0.0 - 1.0)",
                "default": 0.1,
                "minimum": 0.01,
                "maximum": 1.0,
                "ui:widget": "number",
            },
        },
    }

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

    @classmethod
    def _make_hardcoded_calibration(cls) -> _CalibrationResult:
        """Tạo _CalibrationResult với giá trị mặc định an toàn khi không có dữ liệu D1.

        Được dùng làm Tầng 3 (last resort) trong _ensure_calibration() khi:
        - Không đủ dữ liệu D1 để tính calibration mới.
        - Không có calibration cũ nào trong bộ nhớ.

        Giá trị được chọn theo nguyên tắc conservative:
        - sideway_threshold = 0.0  → BBWidth > 0.0 luôn đúng (không block Shield)
        - min_slope = 1e-9         → |slope| > 1e-9 gần như luôn đúng (không block Shield)
        - base_atr = 0.0           → SL/TP sẽ dùng hard_sl_pct thay vì ATR
        - d1_candles_used = 0      → đánh dấu là hardcoded (is_hardcoded_default = True)

        Hệ quả: Shield chỉ còn ADX filter hoạt động thực sự.
        Bot vẫn giao dịch được nhưng thiếu bộ lọc sideway từ D1.

        Returns:
            _CalibrationResult với giá trị mặc định an toàn.
        """
        return _CalibrationResult(
            calibrated_at=datetime.utcnow(),
            base_atr=0.0,
            sideway_threshold=0.0,
            min_slope=1e-9,
            d1_candles_used=0,
        )

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
        # Per-symbol asyncio.Lock — cô lập lock theo từng symbol để tránh bottleneck.
        # Các symbol khác nhau không block lẫn nhau; chỉ cùng 1 symbol mới serialize.
        self._order_states_locks: dict[str, asyncio.Lock] = {}

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

        # Bước 1: Calibration (D1) — chạy nếu chưa có hoặc đã stale.
        # _ensure_calibration() luôn trả về _CalibrationResult (không bao giờ None).
        # Tầng 3 (hardcoded default) được log CRITICAL bên trong _ensure_calibration().
        calibration = await self._ensure_calibration(ohlcv_data, symbol)

        # Cảnh báo mỗi cycle nếu đang dùng hardcoded default
        if calibration.is_hardcoded_default:
            logger.warning(
                f"[ADTS][{symbol}] ⚠️ Đang dùng hardcoded calibration — "
                f"Shield BBWidth/Slope bị vô hiệu hóa. Chỉ ADX filter còn hoạt động."
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

        # Bước 4–5: Đọc order_state + Exit checks trong lock để tránh race condition.
        # Lock bao phủ toàn bộ Read-Modify-Write trên _order_states[symbol]:
        #   - Đọc order_state (Read)
        #   - _check_exits() có thể modify attributes của order_state (Modify)
        #   - pop() khi full_close (Write/Delete)
        # I/O nặng (_ensure_calibration, build_adts_snapshot) nằm ngoài lock.
        async with self._get_order_state_lock(symbol):
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

            # Không có tín hiệu — snapshot reason_parts trong lock để đọc pos_side nhất quán
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
    ) -> _CalibrationResult:
        """Đảm bảo calibration còn hiệu lực — luôn trả về _CalibrationResult (không bao giờ None).

        Triển khai 3 tầng fallback để bot không bao giờ bị tê liệt vì thiếu dữ liệu D1:

        Tầng 1 — Fresh Calibration (bình thường):
            Đủ dữ liệu D1, tính toán thành công → cập nhật self._calibration.

        Tầng 2 — Stale Fallback (dùng calibration cũ):
            Tầng 1 thất bại nhưng self._calibration đã có từ trước (dù is_stale=True)
            → dùng tạm, log WARNING kèm tuổi của calibration cũ.

        Tầng 3 — Hardcoded Default (last resort):
            Cả 2 tầng trên đều thất bại (chưa từng calibrate thành công)
            → tạo _CalibrationResult với giá trị conservative, log CRITICAL.
            Hệ quả: Shield chỉ còn ADX filter, BBWidth/Slope bị vô hiệu hóa.

        Thread-safety: toàn bộ logic nằm trong asyncio.Lock để đảm bảo chỉ 1 coroutine
        chạy calibration tại một thời điểm, ngay cả khi nhiều symbol chạy song song.

        Args:
            intraday_ohlcv: Dữ liệu OHLCV intraday để resample sang D1.
            symbol: Tên symbol (chỉ dùng cho logging).

        Returns:
            _CalibrationResult — luôn có giá trị, không bao giờ None.
        """
        async with self._calibration_lock:
            # Fast path: calibration còn hiệu lực → trả về ngay, không tính lại
            if self._calibration is not None and not self._calibration.is_stale:
                return self._calibration

            # ── Tầng 1: Thử tính calibration mới ────────────────────────────
            logger.info(f"[ADTS][{symbol}] Chạy Daily Calibration...")
            d1_ohlcv = self._resample_to_d1(intraday_ohlcv)

            if d1_ohlcv:
                result = self._run_calibration(d1_ohlcv, symbol)
                if result is not None:
                    self._calibration = result
                    return self._calibration

            # ── Tầng 2: Dùng calibration cũ nếu có (dù stale) ───────────────
            if self._calibration is not None:
                age = self._calibration.age_hours
                logger.warning(
                    f"[ADTS][{symbol}] ⚠️ Calibration mới thất bại — "
                    f"dùng tạm kết quả cũ ({age:.1f}h tuổi, "
                    f"calibrated_at={self._calibration.calibrated_at.strftime('%Y-%m-%d %H:%M')} UTC). "
                    f"Shield vẫn hoạt động đầy đủ với ngưỡng cũ."
                )
                return self._calibration

            # ── Tầng 3: Hardcoded default — last resort ───────────────────────
            logger.critical(
                f"[ADTS][{symbol}] 🚨 Không có calibration nào (fresh lẫn cũ) — "
                f"dùng hardcoded default. "
                f"Shield chỉ còn ADX filter! BBWidth/Slope bị vô hiệu hóa. "
                f"Kiểm tra lookback_candles (cần ≥{self._bbwidth_sma_period * 10 + 100} nến)."
            )
            self._calibration = self._make_hardcoded_calibration()
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
        """Kiểm tra điều kiện Emergency Exit — 2 giai đoạn.

        Giai đoạn 1 (lần đầu vi phạm, emergency_triggered=False):
            Đóng emergency_close_pct (50%), set emergency_triggered=True,
            cập nhật amount_remaining để PnL Giai đoạn 2 chính xác,
            persist state ngay lập tức.

        Giai đoạn 2 (vi phạm tiếp diễn, emergency_triggered=True):
            Đóng 100% phần còn lại (amount_remaining), full_close=True.

        Nhánh Recovery (Shield phục hồi, emergency_triggered=True):
            Reset emergency_triggered=False, tiếp tục giữ vị thế bình thường.

        Điều kiện kích hoạt emergency:
            ADX < emergency_adx_threshold  HOẶC  BBWidth < sideway_threshold.

        Args:
            symbol: Symbol giao dịch.
            snap: ADTSSnapshot tại nến cuối.
            order_state: Trạng thái lệnh đang mở.
            calibration: Kết quả calibration hiện tại.
            shield: Trạng thái Shield hiện tại.

        Returns:
            StrategySignal exit hoặc None nếu không có emergency.
        """
        is_emergency, emg_reason = self._detect_emergency_condition(
            snap, calibration
        )

        # ── Nhánh Recovery: Shield phục hồi sau khi đã trigger ───────────────
        if not is_emergency and order_state.emergency_triggered:
            order_state.emergency_triggered = False
            logger.info(
                f"[ADTS][{symbol}] ✅ Emergency condition cleared — "
                f"Shield phục hồi, reset emergency_triggered. "
                f"Tiếp tục giữ {order_state.amount_remaining:.4f} contracts."
            )
            asyncio.create_task(
                self._persist_order_state(symbol),
                name=f"adts_persist_emg_reset_{symbol}",
            )
            return None

        # ── Không có emergency ────────────────────────────────────────────────
        if not is_emergency:
            return None

        # ── Giai đoạn 2: Emergency tiếp diễn → đóng 100% còn lại ────────────
        if order_state.emergency_triggered:
            reason = (
                f"🚨 Emergency Exit [Giai đoạn 2/2]: {emg_reason} — "
                f"Điều kiện vẫn vi phạm, đóng 100% còn lại "
                f"({order_state.amount_remaining:.4f} contracts)"
            )
            logger.warning(f"[ADTS][{symbol}] {reason}")
            return self._make_exit_signal(
                symbol=symbol, side=order_state.side, price=snap.close,
                reason=reason, partial=False,
                snap=snap, calibration=calibration, shield=shield, full_close=True,
            )

        # ── Giai đoạn 1: Lần đầu vi phạm → đóng emergency_close_pct ─────────
        close_amount = order_state.amount_remaining * self._emergency_close_pct
        remaining_after = order_state.amount_remaining * (1.0 - self._emergency_close_pct)

        reason = (
            f"🚨 Emergency Exit [Giai đoạn 1/2]: {emg_reason} — "
            f"Đóng {self._emergency_close_pct * 100:.0f}% "
            f"({close_amount:.4f} contracts). "
            f"Còn lại {remaining_after:.4f} contracts, theo dõi nến tiếp theo."
        )
        logger.warning(f"[ADTS][{symbol}] {reason}")

        # Cập nhật state để Giai đoạn 2 tính PnL chính xác
        order_state.emergency_triggered = True
        order_state.amount_remaining    = remaining_after
        order_state.update_trailing_stop(snap.close, snap.atr, self._tp2_trail_atr_mult)

        # Persist ngay lập tức — bảo vệ trạng thái trước khi nến tiếp theo
        asyncio.create_task(
            self._persist_order_state(symbol),
            name=f"adts_persist_emg_phase1_{symbol}",
        )

        return self._make_exit_signal(
            symbol=symbol, side=order_state.side, price=snap.close,
            reason=reason, partial=True,
            partial_pct=self._emergency_close_pct,
            snap=snap, calibration=calibration, shield=shield, full_close=False,
        )

    def _detect_emergency_condition(
        self,
        snap:        ADTSSnapshot,
        calibration: _CalibrationResult,
    ) -> tuple[bool, str]:
        """Kiểm tra điều kiện kích hoạt Emergency Exit.

        Tách riêng khỏi _check_emergency_exit() để tuân thủ Single Responsibility
        và giới hạn ≤50 dòng mỗi hàm.

        Args:
            snap: ADTSSnapshot tại nến cuối.
            calibration: Kết quả calibration hiện tại.

        Returns:
            Tuple (is_emergency, reason_str).
            is_emergency=True nếu ADX hoặc BBWidth vi phạm ngưỡng.
        """
        if snap.adx < self._emergency_adx_threshold:
            reason = (
                f"ADX={snap.adx:.1f} < {self._emergency_adx_threshold} "
                f"(xu hướng suy yếu)"
            )
            return True, reason

        if snap.bb_width < calibration.sideway_threshold:
            reason = (
                f"BBWidth={snap.bb_width:.5f} < "
                f"Threshold={calibration.sideway_threshold:.5f} "
                f"(thị trường nén lại)"
            )
            return True, reason

        return False, ""

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

        # Persist state sau khi TP1 hit — đảm bảo không mất khi restart
        asyncio.create_task(
            self._persist_order_state(symbol),
            name=f"adts_persist_tp1_{symbol}",
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
            # Persist trailing stop đã cập nhật dù chưa hit — để không mất khi restart
            asyncio.create_task(
                self._persist_order_state(symbol),
                name=f"adts_persist_trail_{symbol}",
            )
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
            "calibration_is_stale":   calibration.is_stale,
            "calibration_is_default": calibration.is_hardcoded_default,
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

    async def register_order_state(
        self,
        symbol:           str,
        side:             str,
        entry_price:      float,
        amount:           float,
        stop_loss:        float,
        take_profit_1:    float,
        tp2_initial_trail: float,
        atr:              float,
        bot_id:           Optional[int] = None,
    ) -> None:
        """Đăng ký trạng thái lệnh mới sau khi entry được thực thi.

        Được gọi từ bên ngoài (bot_engine hoặc order_manager) sau khi lệnh khớp.
        Tự động persist state vào Trade.signal_metadata để đảm bảo tính nhất quán
        khi bot restart (fix ADTS-001).

        Thread-safety: bọc lock per-symbol để tránh race condition với analyze()
        đang chạy song song cho cùng symbol.

        Args:
            symbol: Symbol giao dịch.
            side: "long" hoặc "short".
            entry_price: Giá vào lệnh.
            amount: Khối lượng lệnh.
            stop_loss: Giá stop loss ban đầu.
            take_profit_1: Giá TP1.
            tp2_initial_trail: Giá trailing stop ban đầu.
            atr: ATR tại thời điểm vào lệnh.
            bot_id: ID của bot (dùng để query Trade khi persist).
        """
        async with self._get_order_state_lock(symbol):
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
        asyncio.create_task(
            self._persist_order_state(symbol, bot_id),
            name=f"adts_persist_{symbol}",
        )

    async def clear_order_state(self, symbol: str) -> None:
        """Xóa order state khi lệnh đã đóng hoàn toàn.

        Thread-safety: bọc lock per-symbol trước khi xóa.
        Sau khi xóa state, lock của symbol cũng được cleanup để tối ưu bộ nhớ —
        lock sẽ được tạo lại tự động nếu symbol được giao dịch lại.

        Args:
            symbol: Symbol giao dịch cần xóa state.
        """
        async with self._get_order_state_lock(symbol):
            self._order_states.pop(symbol, None)
        # Cleanup lock sau khi release — tối ưu bộ nhớ
        # (lock không còn cần thiết khi không có order state)
        self._order_states_locks.pop(symbol, None)
        logger.debug(f"[ADTS][{symbol}] OrderState đã xóa")

    # ── State persistence (fix ADTS-001) ──────────────────────────────────────

    def _get_order_state_lock(self, symbol: str) -> asyncio.Lock:
        """Lấy hoặc tạo asyncio.Lock riêng cho symbol.

        Mỗi symbol có 1 Lock độc lập — các symbol khác nhau không block lẫn nhau.
        Dict assignment trong asyncio là atomic (CPython single-threaded event loop)
        nên không cần lock bảo vệ chính `_order_states_locks` dict.

        Args:
            symbol: Symbol giao dịch (vd: "BTC/USDT").

        Returns:
            asyncio.Lock dành riêng cho symbol này.
        """
        if symbol not in self._order_states_locks:
            self._order_states_locks[symbol] = asyncio.Lock()
        return self._order_states_locks[symbol]

    async def _persist_order_state(
        self, symbol: str, bot_id: Optional[int] = None
    ) -> None:
        """Persist _OrderState hiện tại vào Trade.signal_metadata trong DB.

        Ghi key "adts_order_state" vào signal_metadata của Trade đang mở
        (status='filled', closed_at IS NULL) tương ứng với symbol và bot_id.

        Lỗi được bắt và log WARNING — không để crash cycle chính.

        Args:
            symbol: Symbol giao dịch cần persist state.
            bot_id: ID của bot để lọc đúng Trade record.
        """
        order_state = self._order_states.get(symbol)
        if order_state is None:
            return

        try:
            from src.database.db import get_db
            from src.database.models import Trade
            from sqlalchemy import select

            sym_clean = symbol.replace("/", "").replace(":USDT", "")

            async with get_db() as db:
                query = (
                    select(Trade)
                    .where(
                        Trade.status == "filled",
                        Trade.closed_at == None,  # noqa: E711
                    )
                    .order_by(Trade.created_at.desc())
                    .limit(1)
                )
                if bot_id is not None:
                    query = query.where(Trade.bot_id == bot_id)

                result = await db.execute(query)
                trade = result.scalar_one_or_none()

                if trade is None:
                    logger.debug(
                        f"[ADTS][{symbol}] _persist_order_state: "
                        f"không tìm thấy Trade OPEN (bot_id={bot_id})"
                    )
                    return

                # Merge vào signal_metadata hiện có — không ghi đè toàn bộ
                meta = dict(trade.signal_metadata or {})
                meta["adts_order_state"] = order_state.to_dict()
                trade.signal_metadata = meta

                logger.debug(
                    f"[ADTS][{symbol}] OrderState persisted → Trade #{trade.id} "
                    f"(tp1_hit={order_state.tp1_hit}, "
                    f"sl_moved={order_state.sl_moved_to_entry}, "
                    f"trail={order_state.take_profit_2_trail:.4f})"
                )

        except Exception as exc:
            logger.warning(
                f"[ADTS][{symbol}] _persist_order_state lỗi (bỏ qua): "
                f"{type(exc).__name__}: {exc}"
            )

    async def restore_order_states_from_db(self, bot_id: Optional[int] = None) -> int:
        """Reconstruct _order_states từ các Trade OPEN trong DB khi bot restart.

        Query tất cả Trade có status='filled' và closed_at IS NULL, đọc key
        "adts_order_state" từ signal_metadata để rebuild _order_states dict.

        Nên được gọi trong BotEngine.initialize() sau khi strategy được tạo.

        Thread-safety: I/O DB nằm ngoài lock; mỗi write vào _order_states được
        bọc lock per-symbol riêng để không block các symbol khác.

        Args:
            bot_id: ID của bot để lọc đúng Trade records. None = lấy tất cả.

        Returns:
            Số lượng _OrderState đã được restore thành công.
        """
        restored = 0
        try:
            from src.database.db import get_db
            from src.database.models import Trade
            from sqlalchemy import select

            # I/O DB nằm ngoài lock — không gây bottleneck
            async with get_db() as db:
                query = (
                    select(Trade)
                    .where(
                        Trade.status == "filled",
                        Trade.closed_at == None,  # noqa: E711
                        Trade.strategy == self.STRATEGY_NAME,
                    )
                )
                if bot_id is not None:
                    query = query.where(Trade.bot_id == bot_id)

                result = await db.execute(query)
                open_trades = result.scalars().all()

            for trade in open_trades:
                meta = trade.signal_metadata or {}
                state_dict = meta.get("adts_order_state")
                if not state_dict:
                    logger.warning(
                        f"[ADTS] Trade #{trade.id} {trade.symbol} không có "
                        f"adts_order_state trong metadata — bỏ qua restore"
                    )
                    continue

                try:
                    order_state = _OrderState.from_dict(state_dict)
                    # Lock per-symbol bao phủ chỉ thao tác write vào dict
                    async with self._get_order_state_lock(trade.symbol):
                        self._order_states[trade.symbol] = order_state
                    restored += 1
                    logger.info(
                        f"[ADTS] ✅ Restored OrderState: {trade.symbol} "
                        f"{order_state.side.upper()} entry={order_state.entry_price:.4f} "
                        f"SL={order_state.stop_loss:.4f} "
                        f"tp1_hit={order_state.tp1_hit} "
                        f"trail={order_state.take_profit_2_trail:.4f}"
                    )
                except Exception as exc:
                    logger.warning(
                        f"[ADTS] Trade #{trade.id} {trade.symbol} — "
                        f"lỗi deserialize OrderState: {type(exc).__name__}: {exc}"
                    )

        except Exception as exc:
            logger.error(
                f"[ADTS] restore_order_states_from_db lỗi: "
                f"{type(exc).__name__}: {exc}"
            )

        if restored > 0:
            logger.info(f"[ADTS] Restored {restored} OrderState(s) từ DB sau restart.")
        else:
            logger.info("[ADTS] Không có OrderState nào cần restore (không có Trade OPEN).")

        return restored
