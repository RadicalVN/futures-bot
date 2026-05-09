"""
indicators.py — Technical Indicator Calculations
MA (EMA/SMA), MACD, và các helper functions
"""
import os
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from loguru import logger

# Đọc từ env, mặc định 500
_MACD_SIGNAL_LENGTH = int(os.environ.get("MACD_SIGNAL_LENGTH", 500))


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

def add_custom_sma_to_df(df: pd.DataFrame, fast_len=1, slow_len=5, len_c=200, factor=0.05, bb_length=50, bb_mult=2.0, momentum_n=3) -> pd.DataFrame:
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
    slope_pct_arr = np.zeros(len(df))
    momentum_pct_arr = np.zeros(len(df))
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
        
        slope_pct_arr[i] = ((current_sma - prev_sma) / prev_sma) * 100 if prev_sma != 0 else 0
        momentum_pct_arr[i] = (momentum_diff / projected_current_sma) * 100 if projected_current_sma != 0 else 0
        
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
    df['custom_sma_slope_pct'] = slope_pct_arr
    df['custom_sma_momentum_pct'] = momentum_pct_arr

    # ── Gia tốc n phiên: s[t-2n], s[t-n], s[t] ───────────────────────────────
    momentum_n_state = np.full(len(df), 'yellow', dtype=object)
    momentum_n_pct_arr = np.zeros(len(df))
    min_idx = 2 * momentum_n  # cần ít nhất 2*n phiên trước
    for i in range(min_idx, len(df)):
        sma_t   = basis_arr[i]
        sma_tn  = basis_arr[i - momentum_n]
        sma_t2n = basis_arr[i - 2 * momentum_n]
        if np.isnan(sma_t) or np.isnan(sma_tn) or np.isnan(sma_t2n):
            continue
        projected_n = 2 * sma_tn - sma_t2n
        momentum_n_diff = sma_t - projected_n
        momentum_n_pct_arr[i] = (momentum_n_diff / projected_n) * 100 if projected_n != 0 else 0

        diff_n_older_to_prev = sma_t2n - sma_tn
        diff_n_prev_to_curr  = sma_tn  - sma_t

        if momentum_n_diff == 0:
            momentum_n_state[i] = "yellow"
        elif momentum_n_diff > 0:
            if diff_n_older_to_prev > 0:
                momentum_n_state[i] = "orange" if diff_n_prev_to_curr > 0 else "purple"
            else:
                momentum_n_state[i] = "blue"
        else:
            if diff_n_older_to_prev > 0:
                momentum_n_state[i] = "red"
            else:
                momentum_n_state[i] = "green" if diff_n_prev_to_curr < 0 else "purple"

    df['custom_sma_momentum_n']     = momentum_n_state
    df['custom_sma_momentum_n_pct'] = momentum_n_pct_arr

    return df

def add_custom_macd_to_df(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_length: int = None,
    src: str = "EMA",       # "EMA" | "SMA" — loại MA cho oscillator
    sig_type: str = "EMA",  # "EMA" | "SMA" — loại MA cho signal line
) -> pd.DataFrame:
    """
    Custom MACD - TuanTV1008
    Khác MACD chuẩn:
    - signal_length mặc định lấy từ env MACD_SIGNAL_LENGTH (mặc định 500) → Signal cực mượt
    - Histogram 4 màu: above_grow / above_fall / below_grow / below_fall
    - Momentum cross markers trên MACD line và Signal line (giống Custom SMA)
    """
    if signal_length is None:
        signal_length = _MACD_SIGNAL_LENGTH
    close = df['close']

    # ── Tính MACD line ────────────────────────────────────────────────────────
    if src == "SMA":
        fast_ma = close.rolling(fast).mean()
        slow_ma = close.rolling(slow).mean()
    else:
        fast_ma = close.ewm(span=fast, adjust=False).mean()
        slow_ma = close.ewm(span=slow, adjust=False).mean()

    macd_line = fast_ma - slow_ma

    # ── Tính Signal line ──────────────────────────────────────────────────────
    if sig_type == "SMA":
        signal_line = macd_line.rolling(signal_length).mean()
    else:
        signal_line = macd_line.ewm(span=signal_length, adjust=False).mean()

    # ── Histogram ─────────────────────────────────────────────────────────────
    hist = macd_line - signal_line

    # ── Histogram color: 4 trạng thái ────────────────────────────────────────
    # above_grow  (#26A69A): hist > 0 và đang tăng
    # above_fall  (#B2DFDB): hist > 0 và đang giảm
    # below_grow  (#FFCDD2): hist < 0 và đang tăng (về 0)
    # below_fall  (#FF5252): hist < 0 và đang giảm (xa 0)
    hist_arr = hist.to_numpy()
    hist_color = np.full(len(df), 'above_grow', dtype=object)
    for i in range(1, len(df)):
        h_curr = hist_arr[i]
        h_prev = hist_arr[i - 1]
        if np.isnan(h_curr) or np.isnan(h_prev):
            hist_color[i] = 'above_grow'
        elif h_curr >= 0:
            hist_color[i] = 'above_grow' if h_curr >= h_prev else 'above_fall'
        else:
            hist_color[i] = 'below_grow' if h_curr >= h_prev else 'below_fall'

    # ── Momentum state cho MACD line và Signal line ───────────────────────────
    def _calc_momentum(series_arr: np.ndarray) -> np.ndarray:
        """Tính momentum state giống Custom SMA (yellow/blue/orange/purple/red/green)."""
        state = np.full(len(series_arr), 'yellow', dtype=object)
        for i in range(2, len(series_arr)):
            s0 = series_arr[i]
            s1 = series_arr[i - 1]
            s2 = series_arr[i - 2]
            if np.isnan(s0) or np.isnan(s1) or np.isnan(s2):
                continue
            s0_hope = 2 * s1 - s2          # nội suy tuyến tính
            trend_val = s0 - s0_hope        # momentum diff
            diff_2_1 = s2 - s1              # sma21
            diff_1_0 = s1 - s0              # sma10

            if trend_val == 0:
                state[i] = 'yellow'
            elif trend_val > 0:
                if diff_2_1 > 0:
                    state[i] = 'orange' if diff_1_0 > 0 else 'purple'
                else:
                    state[i] = 'blue'
            else:
                if diff_2_1 > 0:
                    state[i] = 'red'
                else:
                    state[i] = 'green' if diff_1_0 < 0 else 'purple'
        return state

    macd_arr   = macd_line.to_numpy()
    signal_arr = signal_line.to_numpy()

    # ── Slope % cho MACD line và Signal line ──────────────────────────────────
    # slope_pct[i]    = (curr - prev) / |prev| * 100
    # momentum_pct[i] = (curr - projected) / |projected| * 100
    #                   projected = 2*prev - older  (nội suy tuyến tính)
    def _calc_slope_pct(arr: np.ndarray) -> np.ndarray:
        slope = np.zeros(len(arr))
        for i in range(1, len(arr)):
            curr, prev = arr[i], arr[i - 1]
            if np.isnan(curr) or np.isnan(prev) or prev == 0:
                slope[i] = 0.0
            else:
                slope[i] = (curr - prev) / abs(prev) * 100
        return slope

    def _calc_momentum_pct(arr: np.ndarray) -> np.ndarray:
        """Gia tốc %: độ lệch thực tế so với nội suy tuyến tính, chuẩn hoá theo |projected|."""
        mom = np.zeros(len(arr))
        for i in range(2, len(arr)):
            curr, prev, older = arr[i], arr[i - 1], arr[i - 2]
            if np.isnan(curr) or np.isnan(prev) or np.isnan(older):
                continue
            projected = 2 * prev - older
            if projected == 0:
                continue
            mom[i] = (curr - projected) / abs(projected) * 100
        return mom

    df['custom_macd']               = macd_line
    df['custom_macd_signal']        = signal_line
    df['custom_macd_hist']          = hist
    df['custom_macd_hist_color']    = hist_color
    df['custom_macd_momentum']      = _calc_momentum(macd_arr)
    df['custom_macd_sig_momentum']  = _calc_momentum(signal_arr)
    df['custom_macd_slope_pct']     = _calc_slope_pct(macd_arr)
    df['custom_macd_sig_slope_pct'] = _calc_slope_pct(signal_arr)
    df['custom_macd_momentum_pct']      = _calc_momentum_pct(macd_arr)
    df['custom_macd_sig_momentum_pct']  = _calc_momentum_pct(signal_arr)

    return df


def add_adx_to_df(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Tính ADX (Average Directional Index) và thêm vào DataFrame.

    Columns thêm vào:
    - adx        : ADX line (độ mạnh xu hướng, 0–100)
    - adx_plus_di : +DI
    - adx_minus_di: -DI

    period: chu kỳ Wilder smoothing, mặc định 14
    """
    high  = df["high"].to_numpy(dtype=float)
    low   = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n     = len(df)

    plus_dm  = np.zeros(n)
    minus_dm = np.zeros(n)
    tr_arr   = np.zeros(n)

    for i in range(1, n):
        h_diff = high[i]  - high[i - 1]
        l_diff = low[i - 1] - low[i]

        plus_dm[i]  = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
        minus_dm[i] = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0

        tr_arr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )

    # Wilder smoothing (RMA)
    def _wilder_smooth(arr: np.ndarray, p: int) -> np.ndarray:
        out = np.zeros(n)
        # Seed: sum of first p values
        if p < n:
            out[p] = arr[1:p + 1].sum()
            for i in range(p + 1, n):
                out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    atr_s    = _wilder_smooth(tr_arr,   period)
    plus_s   = _wilder_smooth(plus_dm,  period)
    minus_s  = _wilder_smooth(minus_dm, period)

    plus_di  = np.where(atr_s != 0, 100 * plus_s  / atr_s, 0.0)
    minus_di = np.where(atr_s != 0, 100 * minus_s / atr_s, 0.0)

    dx = np.where(
        (plus_di + minus_di) != 0,
        100 * np.abs(plus_di - minus_di) / (plus_di + minus_di),
        0.0,
    )

    # ADX = Wilder smooth của DX
    adx = np.zeros(n)
    start = period * 2  # cần đủ dữ liệu cho cả DM smoothing lẫn ADX smoothing
    if start < n:
        adx[start] = dx[period:start + 1].mean()  # seed ADX
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    df["adx"]         = adx
    df["adx_plus_di"] = plus_di
    df["adx_minus_di"] = minus_di

    return df


def add_bb_to_df(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """
    Tính Bollinger Bands và thêm vào DataFrame.

    Columns thêm vào:
    - bb_upper  : Dải trên  = SMA(period) + mult × std
    - bb_middle : Dải giữa  = SMA(period)
    - bb_lower  : Dải dưới  = SMA(period) - mult × std

    period: chu kỳ SMA, mặc định 20
    mult  : hệ số độ lệch chuẩn, mặc định 2.0
    """
    close = df["close"]
    middle = close.rolling(period).mean()
    std    = close.rolling(period).std(ddof=0)   # population std — giống TradingView

    df["bb_upper"]  = middle + mult * std
    df["bb_middle"] = middle
    df["bb_lower"]  = middle - mult * std

    return df


# ══════════════════════════════════════════════════════════════════════════════
# ADTS Indicators — Dùng chung cho mọi strategy cần ATR, EMA Slope, BBWidth
# ══════════════════════════════════════════════════════════════════════════════

def add_atr_to_df(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Tính ATR (Wilder's RMA) và thêm cột ``atr`` vào DataFrame.

    Dùng chung cho mọi strategy cần ATR (ADTS, trailing stop, ...).
    Thuật toán: True Range → Wilder's smoothing (alpha = 1/period).

    Args:
        df: DataFrame OHLCV với cột high, low, close.
        period: Chu kỳ ATR, mặc định 14.

    Returns:
        DataFrame với cột ``atr`` được thêm vào.
    """
    high  = df["high"]
    low   = df["low"]
    close_prev = df["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low  - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["atr"] = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return df


def add_ema_slope_to_df(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Tính EMA và độ dốc (slope) của EMA, thêm vào DataFrame.

    Thêm 2 cột:
    - ``ema{period}``       : Giá trị EMA tại mỗi nến.
    - ``ema{period}_slope`` : Độ dốc = EMA[i] - EMA[i-1] (tuyệt đối, không phải %).
      Dương = đang tăng, Âm = đang giảm.

    Args:
        df: DataFrame OHLCV với cột close.
        period: Chu kỳ EMA, mặc định 20.

    Returns:
        DataFrame với 2 cột mới được thêm vào.
    """
    ema = df["close"].ewm(span=period, adjust=False).mean()
    df[f"ema{period}"]       = ema
    df[f"ema{period}_slope"] = ema.diff(1)
    return df


def add_bbwidth_to_df(
    df: pd.DataFrame,
    period: int = 20,
    mult: float = 2.0,
) -> pd.DataFrame:
    """Tính Bollinger Bands và BBWidth, thêm vào DataFrame.

    Thêm 4 cột:
    - ``bb_upper``  : Dải trên.
    - ``bb_middle`` : Dải giữa (SMA).
    - ``bb_lower``  : Dải dưới.
    - ``bb_width``  : (Upper - Lower) / Middle — đo độ nén/giãn của thị trường.

    Khác với ``add_bb_to_df``: thêm cột ``bb_width`` để dùng cho The Shield.

    Args:
        df: DataFrame OHLCV với cột close.
        period: Chu kỳ SMA, mặc định 20.
        mult: Hệ số độ lệch chuẩn, mặc định 2.0.

    Returns:
        DataFrame với 4 cột mới được thêm vào.
    """
    close  = df["close"]
    middle = close.rolling(period).mean()
    std    = close.rolling(period).std(ddof=0)
    upper  = middle + mult * std
    lower  = middle - mult * std

    df["bb_upper"]  = upper
    df["bb_middle"] = middle
    df["bb_lower"]  = lower
    df["bb_width"]  = (upper - lower) / middle
    return df


# ── ADTS Snapshot ─────────────────────────────────────────────────────────────

@dataclass
class ADTSSnapshot:
    """Tất cả giá trị indicator ADTS tại nến cuối cùng.

    Được trả về bởi ``build_adts_snapshot()`` và dùng trong:
    - ``ADTSStrategy.prepare_metadata()`` → ExitMonitorService
    - ``ADTSStrategy._evaluate_shield()`` → Entry/Exit logic
    - ``ADTSStrategy._check_emergency_exit()`` → Emergency Exit

    Attributes:
        close, high, low: Giá nến hiện tại.
        atr: ATR(period) — dùng cho SL/TP động.
        adx: ADX(period) — The Shield condition 1.
        bb_width: BBWidth(period, std) — The Shield condition 2.
        ema20: EMA(ema_period) — Entry signal.
        ema20_slope: Độ dốc EMA — The Shield condition 3.
        ema200: EMA(ema200_period) — Trend Filter.
        close_prev: Giá đóng nến trước (để kiểm tra cross).
        ema20_prev: EMA nến trước (để kiểm tra cross).
    """
    close:       float
    high:        float
    low:         float
    atr:         float
    adx:         float
    bb_width:    float
    ema20:       float
    ema20_slope: float
    ema200:      float
    close_prev:  float
    ema20_prev:  float


def build_adts_snapshot(
    df:            pd.DataFrame,
    atr_period:    int   = 14,
    adx_period:    int   = 14,
    ema_period:    int   = 20,
    ema200_period: int   = 200,
    bb_period:     int   = 20,
    bb_std:        float = 2.0,
) -> Optional[ADTSSnapshot]:
    """Tính toán tất cả indicators ADTS và trả về snapshot tại nến cuối.

    Tái sử dụng các hàm ``add_*_to_df`` đã có trong module này.
    Trả về None nếu không đủ dữ liệu hoặc có giá trị NaN.

    Args:
        df: DataFrame OHLCV (chưa cần có indicator columns).
        atr_period: Chu kỳ ATR, mặc định 14.
        adx_period: Chu kỳ ADX, mặc định 14.
        ema_period: Chu kỳ EMA entry signal, mặc định 20.
        ema200_period: Chu kỳ EMA trend filter, mặc định 200.
        bb_period: Chu kỳ Bollinger Bands, mặc định 20.
        bb_std: Hệ số std BB, mặc định 2.0.

    Returns:
        ADTSSnapshot hoặc None nếu không đủ dữ liệu.
    """
    min_required = max(adx_period, bb_period, ema_period, ema200_period) * 2 + 5
    if len(df) < min_required:
        logger.warning(
            f"[build_adts_snapshot] Khong du du lieu: co {len(df)}, can >={min_required}"
        )
        return None

    try:
        # Tái sử dụng các hàm đã có — không duplicate logic
        df = add_atr_to_df(df.copy(), atr_period)
        df = add_adx_to_df(df, adx_period)
        df = add_bbwidth_to_df(df, bb_period, bb_std)
        df = add_ema_slope_to_df(df, ema_period)

        # EMA200 riêng (trend filter)
        df[f"ema{ema200_period}"] = df["close"].ewm(
            span=ema200_period, adjust=False
        ).mean()

        # Lấy giá trị tại nến cuối
        i = len(df) - 1
        vals = {
            "atr":         df["atr"].iloc[i],
            "adx":         df["adx"].iloc[i],
            "bb_width":    df["bb_width"].iloc[i],
            "ema20":       df[f"ema{ema_period}"].iloc[i],
            "ema20_slope": df[f"ema{ema_period}_slope"].iloc[i],
            "ema200":      df[f"ema{ema200_period}"].iloc[i],
        }

        # Kiểm tra NaN
        for name, val in vals.items():
            if np.isnan(float(val)):
                logger.warning(f"[build_adts_snapshot] {name} = NaN, bo qua")
                return None

        return ADTSSnapshot(
            close=float(df["close"].iloc[i]),
            high=float(df["high"].iloc[i]),
            low=float(df["low"].iloc[i]),
            atr=float(vals["atr"]),
            adx=float(vals["adx"]),
            bb_width=float(vals["bb_width"]),
            ema20=float(vals["ema20"]),
            ema20_slope=float(vals["ema20_slope"]),
            ema200=float(vals["ema200"]),
            close_prev=float(df["close"].iloc[i - 1]),
            ema20_prev=float(df[f"ema{ema_period}"].iloc[i - 1]),
        )

    except Exception as exc:
        logger.error(
            f"[build_adts_snapshot] Loi tinh indicator: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
