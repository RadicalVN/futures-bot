"""
adts/config.py — Quản lý cấu hình ADTS qua biến môi trường

Tất cả tham số có thể override qua env vars với prefix ADTS_.
Ví dụ: ADTS_RISK_PCT=0.02 sẽ override risk_pct mặc định.

Sử dụng:
    from src.strategies.adts.config import load_adts_config
    cfg = load_adts_config()          # Dùng env vars + defaults
    cfg = load_adts_config(overrides) # Merge với dict từ DB bot parameters
"""
from __future__ import annotations

import os
from typing import Any

from .models import ADTSConfig


# ── Mapping env var → field name ──────────────────────────────────────────────
_ENV_MAP: dict[str, str] = {
    "ADTS_ATR_PERIOD": "atr_period",
    "ADTS_ADX_PERIOD": "adx_period",
    "ADTS_EMA_PERIOD": "ema_period",
    "ADTS_EMA200_PERIOD": "ema200_period",
    "ADTS_BB_PERIOD": "bb_period",
    "ADTS_BB_STD": "bb_std",
    "ADTS_BBWIDTH_SMA_PERIOD": "bbwidth_sma_period",
    "ADTS_ADX_THRESHOLD": "adx_threshold",
    "ADTS_BBWIDTH_THRESHOLD_FACTOR": "bbwidth_threshold_factor",
    "ADTS_MIN_SLOPE_ATR_FACTOR": "min_slope_atr_factor",
    "ADTS_RISK_PCT": "risk_pct",
    "ADTS_SL_ATR_MULT": "sl_atr_mult",
    "ADTS_HARD_SL_PCT": "hard_sl_pct",
    "ADTS_TP1_RR": "tp1_rr",
    "ADTS_TP1_CLOSE_PCT": "tp1_close_pct",
    "ADTS_TP2_TRAIL_ATR_MULT": "tp2_trail_atr_mult",
    "ADTS_EMERGENCY_ADX_THRESHOLD": "emergency_adx_threshold",
    "ADTS_EMERGENCY_CLOSE_PCT": "emergency_close_pct",
    "ADTS_D1_LOOKBACK": "d1_lookback",
    "ADTS_CALIBRATION_INTERVAL_HOURS": "calibration_interval_hours",
    "ADTS_LEVERAGE": "leverage",
    "ADTS_MAX_OPEN_POSITIONS": "max_open_positions",
    "ADTS_MIN_NOTIONAL": "min_notional",
}

# Fields có kiểu int
_INT_FIELDS = {
    "atr_period", "adx_period", "ema_period", "ema200_period", "bb_period",
    "bbwidth_sma_period", "d1_lookback", "leverage", "max_open_positions",
}


def _read_env_overrides() -> dict[str, Any]:
    """Đọc tất cả ADTS_* env vars và trả về dict tham số."""
    overrides: dict[str, Any] = {}
    for env_key, field_name in _ENV_MAP.items():
        raw = os.getenv(env_key)
        if raw is not None:
            try:
                if field_name in _INT_FIELDS:
                    overrides[field_name] = int(raw)
                else:
                    overrides[field_name] = float(raw)
            except ValueError:
                pass  # Bỏ qua giá trị không hợp lệ
    return overrides


def load_adts_config(bot_params: dict | None = None) -> ADTSConfig:
    """
    Tạo ADTSConfig với thứ tự ưu tiên:
      1. Defaults (từ ADTSConfig field defaults)
      2. Env vars (ADTS_*)
      3. bot_params (từ DB bot.parameters — override cao nhất)

    Args:
        bot_params: Dict tham số từ bot.parameters trong DB (optional)

    Returns:
        ADTSConfig đã validate
    """
    merged: dict[str, Any] = {}

    # Layer 2: Env vars
    merged.update(_read_env_overrides())

    # Layer 3: Bot params từ DB (override cao nhất)
    if bot_params:
        known_fields = set(ADTSConfig.model_fields.keys())
        for k, v in bot_params.items():
            if k in known_fields and v is not None:
                merged[k] = v

    return ADTSConfig(**merged)


# ── Default config block cho config.yaml ─────────────────────────────────────
ADTS_DEFAULT_YAML_BLOCK = """
# ── ADTS Strategy — Adaptive Dynamic Trend & Shield ──────────────────────────
strategy:
  name: adts

  # Indicator periods
  atr_period: 14
  adx_period: 14
  ema_period: 20
  ema200_period: 200      # EMA200 Trend Filter — Long trên, Short dưới
  bb_period: 20
  bb_std: 2.0
  bbwidth_sma_period: 200

  # The Shield thresholds
  # ADX hạ xuống 20 để tăng cơ hội vào lệnh
  # BBWidth siết chặt hơn (factor=1.0 thay vì 0.85) để chỉ đánh khi có nén thật sự
  adx_threshold: 20.0
  bbwidth_threshold_factor: 1.0
  min_slope_atr_factor: 0.05

  # Risk management
  risk_pct: 0.01          # 1% tài khoản mỗi lệnh
  sl_atr_mult: 1.5        # SL động = 1.5 × ATR
  hard_sl_pct: 0.03       # Hard SL = 3% giá entry (tối đa). SL thực = min(ATR SL, Hard SL)
  tp1_rr: 1.2             # TP1 R:R = 1:1.2
  tp1_close_pct: 0.5      # Chốt 50% tại TP1
  tp2_trail_atr_mult: 2.0 # Trailing Stop = 2.0 × ATR

  # Emergency exit
  emergency_adx_threshold: 20.0
  emergency_close_pct: 0.5  # Đóng 50% khi emergency

  # Calibration
  d1_lookback: 300
  calibration_interval_hours: 24.0

  # Leverage & sizing
  leverage: 5
  max_open_positions: 3
  min_notional: 5.0     # USDT notional tối thiểu còn lại sau partial close
"""
