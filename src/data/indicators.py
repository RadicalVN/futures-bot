"""
indicators.py — Technical Indicator Calculations
MA (EMA/SMA), MACD, và các helper functions
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class MAValues:
    fast: float
    slow: float
    fast_prev: float
    slow_prev: float

    @property
    def golden_cross(self) -> bool:
        """Fast MA vừa vượt lên trên Slow MA"""
        return self.fast_prev <= self.slow_prev and self.fast > self.slow

    @property
    def death_cross(self) -> bool:
        """Fast MA vừa cắt xuống dưới Slow MA"""
        return self.fast_prev >= self.slow_prev and self.fast < self.slow

    @property
    def bullish(self) -> bool:
        """Fast MA đang trên Slow MA"""
        return self.fast > self.slow

    @property
    def bearish(self) -> bool:
        """Fast MA đang dưới Slow MA"""
        return self.fast < self.slow


@dataclass
class MACDValues:
    macd: float
    signal: float
    histogram: float
    macd_prev: float
    signal_prev: float

    @property
    def bullish_cross(self) -> bool:
        """MACD vừa vượt lên trên Signal"""
        return self.macd_prev <= self.signal_prev and self.macd > self.signal

    @property
    def bearish_cross(self) -> bool:
        """MACD vừa cắt xuống dưới Signal"""
        return self.macd_prev >= self.signal_prev and self.macd < self.signal

    @property
    def is_positive(self) -> bool:
        return self.macd > 0

    @property
    def is_negative(self) -> bool:
        return self.macd < 0


def ohlcv_to_dataframe(ohlcv_data: list) -> pd.DataFrame:
    """
    Chuyển dữ liệu OHLCV từ ccxt thành DataFrame
    Input: [[timestamp, open, high, low, close, volume], ...]
    """
    df = pd.DataFrame(
        ohlcv_data,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    return df


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average"""
    return series.rolling(window=period).mean()


def calculate_ma(series: pd.Series, period: int, ma_type: str = "EMA") -> pd.Series:
    """MA wrapper — chọn EMA hoặc SMA"""
    if ma_type.upper() == "EMA":
        return calculate_ema(series, period)
    elif ma_type.upper() == "SMA":
        return calculate_sma(series, period)
    else:
        raise ValueError(f"MA type không hợp lệ: {ma_type}. Dùng 'EMA' hoặc 'SMA'")


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Tính MACD
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def get_ma_values(
    df: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    ma_type: str = "EMA",
) -> Optional[MAValues]:
    """
    Tính MA values từ DataFrame và trả về current + previous values
    """
    if len(df) < slow_period + 2:
        logger.warning(f"Không đủ dữ liệu để tính MA (cần {slow_period + 2} nến)")
        return None

    close = df["close"]
    fast_ma = calculate_ma(close, fast_period, ma_type)
    slow_ma = calculate_ma(close, slow_period, ma_type)

    return MAValues(
        fast=float(fast_ma.iloc[-1]),
        slow=float(slow_ma.iloc[-1]),
        fast_prev=float(fast_ma.iloc[-2]),
        slow_prev=float(slow_ma.iloc[-2]),
    )


def get_macd_values(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[MACDValues]:
    """
    Tính MACD values từ DataFrame và trả về current + previous values
    """
    if len(df) < slow + signal + 2:
        logger.warning("Không đủ dữ liệu để tính MACD")
        return None

    close = df["close"]
    macd_line, signal_line, histogram = calculate_macd(close, fast, slow, signal)

    return MACDValues(
        macd=float(macd_line.iloc[-1]),
        signal=float(signal_line.iloc[-1]),
        histogram=float(histogram.iloc[-1]),
        macd_prev=float(macd_line.iloc[-2]),
        signal_prev=float(signal_line.iloc[-2]),
    )


def add_indicators_to_df(
    df: pd.DataFrame,
    ma_fast: int = 12,
    ma_slow: int = 26,
    ma_type: str = "EMA",
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """
    Thêm tất cả indicators vào DataFrame (dùng cho dashboard/charting)
    """
    close = df["close"]

    df[f"ma_fast"] = calculate_ma(close, ma_fast, ma_type)
    df[f"ma_slow"] = calculate_ma(close, ma_slow, ma_type)

    macd_line, signal_line, histogram = calculate_macd(close, macd_fast, macd_slow, macd_signal)
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_histogram"] = histogram

    return df

def add_custom_sma_to_df(df: pd.DataFrame, fast_len=1, slow_len=5, len_c=200, factor=0.05, bb_length=50, bb_mult=2.0) -> pd.DataFrame:
    close = df['close']
    fastC = close.rolling(fast_len).mean()
    slowC = close.rolling(slow_len).mean()
    closeC = (fastC + slowC).rolling(len_c).mean()

    c5 = closeC / 2
    log_f2 = np.log(10)
    up = c5 - log_f2
    dn = c5 + log_f2

    n = dn.to_numpy()
    x = up.to_numpy()
    c5_arr = c5.to_numpy()
    
    trendx = np.zeros(len(df))
    hb = np.zeros(len(df))
    lb = np.zeros(len(df))
    
    c_count = 0
    first_valid = np.where(~np.isnan(c5_arr))[0]
    if len(first_valid) > 0:
        for i in range(first_valid[0], len(df)):
            curr_n, curr_x, curr_c5 = n[i], x[i], c5_arr[i]
            if c_count == 0:
                lb[i] = curr_n; hb[i] = curr_x
            elif c_count == 1:
                if curr_x >= hb[i-1]:
                    hb[i] = curr_x; trendx[i] = 1
                else:
                    lb[i] = curr_n; trendx[i] = -1
            else:
                if trendx[i-1] > 0:
                    if curr_x >= hb[i-1]:
                        hb[i] = curr_x; trendx[i] = trendx[i-1]
                    else:
                        if curr_n < hb[i-1] - hb[i-1] * factor:
                            lb[i] = curr_n; trendx[i] = -1
                        else:
                            hb[i] = hb[i-1]; lb[i] = lb[i-1]; trendx[i] = trendx[i-1]
                else:
                    if curr_n <= lb[i-1]:
                        lb[i] = curr_n; trendx[i] = trendx[i-1]
                    else:
                        if curr_x > lb[i-1] + lb[i-1] * factor:
                            hb[i] = curr_x; trendx[i] = 1
                        else:
                            hb[i] = hb[i-1]; lb[i] = lb[i-1]; trendx[i] = trendx[i-1]
            c_count += 1
            
    df['custom_sma_up'] = hb
    df['custom_sma_dn'] = lb
    df['custom_sma_trend'] = trendx
    
    basis = close.rolling(bb_length).mean()
    df['custom_sma_basis'] = basis
    
    momentum_state = np.full(len(df), 'Chưa rõ', dtype=object)
    basis_arr = basis.to_numpy()
    for i in range(2, len(df)):
        if np.isnan(basis_arr[i-2]):
            continue
        
        current_sma = basis_arr[i]
        prev_sma = basis_arr[i-1]
        older_sma = basis_arr[i-2]
        
        diff_older_to_prev = older_sma - prev_sma
        diff_prev_to_curr = prev_sma - current_sma
        projected_current_sma = 2 * prev_sma - older_sma
        momentum_diff = current_sma - projected_current_sma
        
        if momentum_diff == 0:
            momentum_state[i] = "yellow"
        elif momentum_diff > 0:
            if diff_older_to_prev > 0:
                if diff_prev_to_curr > 0:
                    momentum_state[i] = "orange"
                else:
                    momentum_state[i] = "purple"
            else:
                momentum_state[i] = "blue"
        else:
            if diff_older_to_prev > 0:
                momentum_state[i] = "red"
            else:
                if diff_prev_to_curr < 0:
                    momentum_state[i] = "green"
                else:
                    momentum_state[i] = "purple"
                    
    df['custom_sma_momentum'] = momentum_state
    
    return df

def add_custom_macd_to_df(df: pd.DataFrame, fast=12, slow=26, sig=9, src="EMA", sig_type="EMA") -> pd.DataFrame:
    close = df['close']
    if src == "SMA":
        fast_ma = close.rolling(fast).mean()
        slow_ma = close.rolling(slow).mean()
    else:
        fast_ma = close.ewm(span=fast, adjust=False).mean()
        slow_ma = close.ewm(span=slow, adjust=False).mean()

    macd = fast_ma - slow_ma

    if sig_type == "SMA":
        signal_line = macd.rolling(sig).mean()
    else:
        signal_line = macd.ewm(span=sig, adjust=False).mean()

    df['custom_macd'] = macd
    df['custom_macd_signal'] = signal_line
    return df
