"""
adts/indicators.py — Tính toán indicator cho ADTS trên khung intraday

Cung cấp:
  - calculate_adx()       : ADX(14) — The Shield condition 1
  - calculate_bbwidth()   : BBWidth hiện tại — The Shield condition 2
  - calculate_ema_slope() : Độ dốc EMA20 — The Shield condition 3 + Entry signal
  - calculate_atr()       : ATR intraday — Dynamic SL/TP
  - build_indicator_snapshot(): Tổng hợp tất cả indicator cần thiết
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


# ── ATR ───────────────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR với Wilder's smoothing (RMA)."""
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

    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


# ── ADX ───────────────────────────────────────────────────────────────────────

def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index (Wilder's method).
    ADX = RMA(|DI+ - DI-| / (DI+ + DI-) * 100, period)
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    high_prev = high.shift(1)
    low_prev = low.shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional Movement
    up_move = high - high_prev
    down_move = low_prev - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    # Wilder's smoothing
    alpha = 1.0 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm_s.ewm(alpha=alpha, adjust=False).mean() / atr_w
    minus_di = 100 * minus_dm_s.ewm(alpha=alpha, adjust=False).mean() / atr_w

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx


# ── Bollinger Band Width ───────────────────────────────────────────────────────

def calculate_bbwidth(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> pd.Series:
    """BBWidth = (Upper - Lower) / Middle."""
    close = df["close"]
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    return (upper - lower) / middle


# ── EMA Slope ─────────────────────────────────────────────────────────────────

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """EMA chuẩn."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_ema_slope(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Độ dốc EMA = EMA[i] - EMA[i-1] (giá trị tuyệt đối, không phải %).
    Dương = đang tăng, Âm = đang giảm.
    """
    ema = calculate_ema(df["close"], period)
    return ema.diff(1)


# ── Snapshot ──────────────────────────────────────────────────────────────────

@dataclass
class IndicatorSnapshot:
    """Tất cả giá trị indicator tại nến cuối cùng."""
    close: float
    high: float
    low: float
    atr: float
    adx: float
    bb_width: float
    ema20: float
    ema20_slope: float
    ema200: float           # EMA200 — Trend Filter: Long trên, Short dưới
    # Giá trị nến trước (để kiểm tra cross)
    close_prev: float
    ema20_prev: float


def build_indicator_snapshot(
    df: pd.DataFrame,
    atr_period: int = 14,
    adx_period: int = 14,
    ema_period: int = 20,
    ema200_period: int = 200,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> Optional[IndicatorSnapshot]:
    """
    Tính toán tất cả indicator cần thiết cho ADTS và trả về snapshot.

    Args:
        df: DataFrame OHLCV với index là timestamp
        atr_period, adx_period, ema_period, ema200_period, bb_period, bb_std: tham số indicator

    Returns:
        IndicatorSnapshot hoặc None nếu không đủ dữ liệu
    """
    min_required = max(adx_period, bb_period, ema_period, ema200_period) * 2 + 5
    if len(df) < min_required:
        logger.warning(
            f"[ADTS Indicators] Không đủ dữ liệu: có {len(df)}, cần ≥{min_required}"
        )
        return None

    try:
        atr_s   = calculate_atr(df, atr_period)
        adx_s   = calculate_adx(df, adx_period)
        bbw_s   = calculate_bbwidth(df, bb_period, bb_std)
        ema_s   = calculate_ema(df["close"], ema_period)
        slope_s = calculate_ema_slope(df, ema_period)
        ema200_s = calculate_ema(df["close"], ema200_period)

        atr_val    = float(atr_s.iloc[-1])
        adx_val    = float(adx_s.iloc[-1])
        bbw_val    = float(bbw_s.iloc[-1])
        ema_val    = float(ema_s.iloc[-1])
        slope_val  = float(slope_s.iloc[-1])
        ema200_val = float(ema200_s.iloc[-1])
        ema_prev   = float(ema_s.iloc[-2])
        close_curr = float(df["close"].iloc[-1])
        close_prev = float(df["close"].iloc[-2])
        high_curr  = float(df["high"].iloc[-1])
        low_curr   = float(df["low"].iloc[-1])

        # Kiểm tra NaN
        for name, val in [
            ("ATR", atr_val), ("ADX", adx_val), ("BBWidth", bbw_val),
            ("EMA20", ema_val), ("EMA20_Slope", slope_val), ("EMA200", ema200_val),
        ]:
            if np.isnan(val):
                logger.warning(f"[ADTS Indicators] {name} = NaN, bỏ qua")
                return None

        return IndicatorSnapshot(
            close=close_curr,
            high=high_curr,
            low=low_curr,
            atr=atr_val,
            adx=adx_val,
            bb_width=bbw_val,
            ema20=ema_val,
            ema20_slope=slope_val,
            ema200=ema200_val,
            close_prev=close_prev,
            ema20_prev=ema_prev,
        )

    except Exception as e:
        logger.error(f"[ADTS Indicators] Lỗi tính indicator: {type(e).__name__}: {e}")
        return None
