"""
adts/models.py — Pydantic DTOs cho chiến lược ADTS
Adaptive Dynamic Trend & Shield

Định nghĩa schema cho:
  - OHLCVCandle: dữ liệu nến đầu vào
  - ADTSConfig: tham số cấu hình chiến lược
  - CalibrationResult: kết quả hiệu chỉnh hàng ngày
  - ShieldState: trạng thái bộ lọc sideway
  - OrderState: trạng thái lệnh đang mở
  - PositionPlanADTS: kế hoạch vào lệnh với SL/TP động
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── OHLCV ─────────────────────────────────────────────────────────────────────

class OHLCVCandle(BaseModel):
    """Một nến OHLCV đã được validate."""
    timestamp: int = Field(..., description="Unix timestamp (ms)")
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(..., ge=0)

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v: float, info) -> float:
        low = info.data.get("low")
        if low is not None and v < low:
            raise ValueError(f"high ({v}) phải >= low ({low})")
        return v

    @classmethod
    def from_ccxt(cls, row: list) -> "OHLCVCandle":
        """Tạo từ row ccxt: [ts, open, high, low, close, volume]."""
        return cls(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )


# ── Config ────────────────────────────────────────────────────────────────────

class ADTSConfig(BaseModel):
    """Tham số cấu hình đầy đủ cho chiến lược ADTS."""

    # ── Indicator periods ─────────────────────────────────────────────────────
    atr_period: int = Field(14, ge=2, description="Chu kỳ ATR cho D1 calibration")
    adx_period: int = Field(14, ge=2, description="Chu kỳ ADX (The Shield)")
    ema_period: int = Field(20, ge=2, description="Chu kỳ EMA cho entry signal")
    ema200_period: int = Field(200, ge=10, description="Chu kỳ EMA200 cho Trend Filter (Long trên, Short dưới)")
    bb_period: int = Field(20, ge=2, description="Chu kỳ Bollinger Bands")
    bb_std: float = Field(2.0, gt=0, description="Số lần độ lệch chuẩn BB")
    bbwidth_sma_period: int = Field(200, ge=10, description="Chu kỳ SMA của BBWidth cho Sideway_Threshold")

    # ── Shield thresholds ─────────────────────────────────────────────────────
    adx_threshold: float = Field(
        20.0, gt=0,
        description="ADX tối thiểu để vào lệnh. Hạ xuống 20 để tăng cơ hội, "
                    "bù lại bằng BBWidth stricter (bbwidth_threshold_factor=1.0)"
    )
    bbwidth_threshold_factor: float = Field(
        1.0, gt=0, le=2.0,
        description="Hệ số nhân SMA(BBWidth) để tính Sideway_Threshold. "
                    "1.0 = chỉ vào khi BBWidth > trung bình (stricter hơn 0.85)"
    )
    min_slope_atr_factor: float = Field(
        0.05, gt=0,
        description="Hệ số ATR để tính Min_Slope (Base_ATR * factor / 5)"
    )

    # ── Risk management ───────────────────────────────────────────────────────
    risk_pct: float = Field(0.01, gt=0, le=0.1, description="% tài khoản rủi ro mỗi lệnh (1%)")
    sl_atr_mult: float = Field(1.5, gt=0, description="Hệ số ATR cho Stop Loss động")
    hard_sl_pct: float = Field(
        0.03, gt=0, le=0.5,
        description="Hard Stop Loss tối đa tính theo % giá entry (mặc định 3%). "
                    "SL thực tế = min(ATR SL, Hard SL) — lấy mức nào gần entry hơn. "
                    "Ngăn chặn lệnh thua lỗ vô tận khi ATR quá lớn."
    )
    tp1_rr: float = Field(1.2, gt=0, description="R:R cho TP1 (chốt 50%)")
    tp1_close_pct: float = Field(0.5, gt=0, le=1.0, description="% khối lượng chốt tại TP1")
    tp2_trail_atr_mult: float = Field(2.0, gt=0, description="Hệ số ATR cho Trailing Stop TP2")

    # ── Emergency exit ────────────────────────────────────────────────────────
    emergency_adx_threshold: float = Field(
        20.0, gt=0,
        description="ADX cắt xuống dưới ngưỡng này → Emergency Exit"
    )
    emergency_close_pct: float = Field(
        0.5, gt=0, le=1.0,
        description="% khối lượng đóng khi Emergency Exit"
    )

    # ── Calibration ───────────────────────────────────────────────────────────
    d1_lookback: int = Field(300, ge=50, description="Số nến D1 để tính calibration")
    calibration_interval_hours: float = Field(
        24.0, gt=0,
        description="Chu kỳ hiệu chỉnh lại tham số (giờ)"
    )

    # ── Leverage & sizing ─────────────────────────────────────────────────────
    leverage: int = Field(5, ge=1, le=125)
    max_open_positions: int = Field(3, ge=1)
    min_notional: float = Field(
        5.0, gt=0,
        description="Giá trị notional tối thiểu (USDT) của phần còn lại sau partial close. "
                    "Nếu phần còn lại < min_notional → đóng toàn bộ thay vì partial."
    )

    @classmethod
    def from_dict(cls, d: dict) -> "ADTSConfig":
        """Tạo config từ dict tham số bot (bỏ qua key không liên quan)."""
        known = cls.model_fields.keys()
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ── Calibration ───────────────────────────────────────────────────────────────

class CalibrationResult(BaseModel):
    """Kết quả hiệu chỉnh hàng ngày từ dữ liệu D1."""
    calibrated_at: datetime
    base_atr: float = Field(..., gt=0, description="ATR(14) trên D1")
    sideway_threshold: float = Field(..., gt=0, description="SMA(BBWidth, 200) * 0.85")
    min_slope: float = Field(..., gt=0, description="Base_ATR * 0.05 / 5")
    d1_candles_used: int = Field(..., ge=1)

    @property
    def is_stale(self) -> bool:
        """True nếu calibration đã quá 26 giờ (buffer 2h)."""
        age_hours = (datetime.utcnow() - self.calibrated_at).total_seconds() / 3600
        return age_hours > 26.0


# ── Shield ────────────────────────────────────────────────────────────────────

class ShieldState(BaseModel):
    """Trạng thái bộ lọc sideway tại một thời điểm."""
    adx: float
    bb_width: float
    ema20_slope: float
    adx_ok: bool
    bbwidth_ok: bool
    slope_ok: bool

    @property
    def passed(self) -> bool:
        """True khi tất cả 3 điều kiện Shield đều thỏa."""
        return self.adx_ok and self.bbwidth_ok and self.slope_ok

    @property
    def summary(self) -> str:
        flags = [
            f"ADX={self.adx:.1f}({'✓' if self.adx_ok else '✗'})",
            f"BBW={self.bb_width:.5f}({'✓' if self.bbwidth_ok else '✗'})",
            f"Slope={self.ema20_slope:+.6f}({'✓' if self.slope_ok else '✗'})",
        ]
        status = "PASS" if self.passed else "BLOCK"
        return f"Shield[{status}] {' | '.join(flags)}"


# ── Order State ───────────────────────────────────────────────────────────────

class OrderState(BaseModel):
    """Trạng thái đầy đủ của một lệnh đang mở theo ADTS."""
    symbol: str
    side: str = Field(..., pattern="^(long|short)$")
    entry_price: float = Field(..., gt=0)
    amount_total: float = Field(..., gt=0, description="Tổng khối lượng ban đầu")
    amount_remaining: float = Field(..., gt=0, description="Khối lượng còn lại sau TP1")
    stop_loss: float = Field(..., gt=0)
    take_profit_1: float = Field(..., gt=0)
    take_profit_2_trail: float = Field(..., gt=0, description="Giá trailing stop hiện tại")
    atr_at_entry: float = Field(..., gt=0)
    tp1_hit: bool = Field(False, description="Đã chốt 50% tại TP1 chưa")
    sl_moved_to_entry: bool = Field(False, description="Đã dời SL về entry sau TP1 chưa")
    opened_at: datetime = Field(default_factory=datetime.utcnow)

    def update_trailing_stop(self, current_price: float, atr: float, mult: float) -> float:
        """
        Cập nhật trailing stop theo ATR.
        Long: trail = current_price - mult * atr (chỉ tăng, không giảm)
        Short: trail = current_price + mult * atr (chỉ giảm, không tăng)
        Returns: giá trailing stop mới.
        """
        if self.side == "long":
            new_trail = current_price - mult * atr
            self.take_profit_2_trail = max(self.take_profit_2_trail, new_trail)
        else:
            new_trail = current_price + mult * atr
            self.take_profit_2_trail = min(self.take_profit_2_trail, new_trail)
        return self.take_profit_2_trail


# ── Position Plan ─────────────────────────────────────────────────────────────

class PositionPlanADTS(BaseModel):
    """Kế hoạch vào lệnh với SL/TP động theo ATR."""
    symbol: str
    side: str = Field(..., pattern="^(long|short)$")
    entry_price: float = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit_1: float = Field(..., gt=0)
    take_profit_2_initial_trail: float = Field(..., gt=0)
    atr: float = Field(..., gt=0)
    risk_usdt: float = Field(..., gt=0, description="USDT rủi ro thực tế")
    leverage: int = Field(..., ge=1)

    @property
    def sl_distance(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def tp1_distance(self) -> float:
        return abs(self.entry_price - self.take_profit_1)

    @property
    def rr_ratio(self) -> float:
        return self.tp1_distance / self.sl_distance if self.sl_distance > 0 else 0.0
