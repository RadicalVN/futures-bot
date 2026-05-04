"""
adts/scanner.py — Daily Calibration Module

Cứ mỗi 24h, tính lại các tham số động từ dữ liệu D1:
  - Base_ATR  = ATR(14) trên khung D1
  - Sideway_Threshold = SMA(BBWidth(20, 2), 200) * 0.85
  - Min_Slope = (Base_ATR * 0.05) / 5

Logging: Calibration → kết quả từng bước
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from .models import ADTSConfig, CalibrationResult


# ── ATR ───────────────────────────────────────────────────────────────────────

def _calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Average True Range (Wilder's smoothing).
    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Wilder's smoothing (RMA): alpha = 1/period
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


# ── Bollinger Band Width ───────────────────────────────────────────────────────

def _calculate_bbwidth(df: pd.DataFrame, period: int, std_mult: float) -> pd.Series:
    """
    BBWidth = (Upper - Lower) / Middle
    Middle = SMA(close, period)
    Upper  = Middle + std_mult * std(close, period)
    Lower  = Middle - std_mult * std(close, period)
    """
    close = df["close"]
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    bbwidth = (upper - lower) / middle
    return bbwidth


# ── Calibration ───────────────────────────────────────────────────────────────

def run_calibration(
    d1_ohlcv: list,
    config: ADTSConfig,
    symbol: str = "",
) -> Optional[CalibrationResult]:
    """
    Thực hiện hiệu chỉnh tham số động từ dữ liệu D1.

    Args:
        d1_ohlcv: Dữ liệu OHLCV D1 từ ccxt [[ts, o, h, l, c, v], ...]
        config: Cấu hình ADTS
        symbol: Tên symbol (chỉ dùng cho logging)

    Returns:
        CalibrationResult hoặc None nếu không đủ dữ liệu
    """
    tag = f"[Calibration][{symbol}]" if symbol else "[Calibration]"
    logger.info(f"{tag} Bắt đầu hiệu chỉnh với {len(d1_ohlcv)} nến D1")

    # ── Bước 1: Chuyển sang DataFrame ────────────────────────────────────────
    if len(d1_ohlcv) < config.bbwidth_sma_period + config.atr_period + 10:
        min_required = config.bbwidth_sma_period + config.atr_period + 10
        logger.warning(
            f"{tag} Không đủ dữ liệu D1: có {len(d1_ohlcv)}, cần ≥{min_required}"
        )
        return None

    df = pd.DataFrame(
        d1_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    df.set_index("timestamp", inplace=True)

    # ── Bước 2: Tính Base_ATR = ATR(14) trên D1 ──────────────────────────────
    atr_series = _calculate_atr(df, config.atr_period)
    base_atr = float(atr_series.iloc[-1])

    if np.isnan(base_atr) or base_atr <= 0:
        logger.error(f"{tag} Base_ATR không hợp lệ: {base_atr}")
        return None

    logger.debug(f"{tag} Base_ATR(D1, {config.atr_period}) = {base_atr:.4f}")

    # ── Bước 3: Tính Sideway_Threshold = SMA(BBWidth(20,2), 200) * 0.85 ──────
    bbwidth_series = _calculate_bbwidth(df, config.bb_period, config.bb_std)
    bbwidth_sma = bbwidth_series.rolling(window=config.bbwidth_sma_period).mean()
    bbwidth_sma_val = float(bbwidth_sma.iloc[-1])

    if np.isnan(bbwidth_sma_val) or bbwidth_sma_val <= 0:
        logger.error(f"{tag} BBWidth SMA không hợp lệ: {bbwidth_sma_val}")
        return None

    sideway_threshold = bbwidth_sma_val * config.bbwidth_threshold_factor
    logger.debug(
        f"{tag} BBWidth_SMA({config.bbwidth_sma_period}) = {bbwidth_sma_val:.6f} "
        f"→ Sideway_Threshold = {sideway_threshold:.6f}"
    )

    # ── Bước 4: Tính Min_Slope = (Base_ATR * 0.05) / 5 ──────────────────────
    min_slope = (base_atr * config.min_slope_atr_factor) / 5.0
    logger.debug(f"{tag} Min_Slope = {min_slope:.8f}")

    result = CalibrationResult(
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
