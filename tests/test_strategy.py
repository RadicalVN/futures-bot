"""
test_strategy.py — Unit Tests cho Strategy và Indicators
Chạy: pytest tests/ -v
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.data.indicators import (
    ohlcv_to_dataframe,
    get_ma_values,
    get_macd_values,
    calculate_ema,
    calculate_macd,
)
from src.strategies.ma_macd import MaMacdStrategy
from src.strategies.base_strategy import StrategySignal


# ─── Fixtures ─────────────────────────────────────────────────────────

def make_ohlcv(n: int = 200, trend: str = "up") -> list:
    """Tạo dữ liệu OHLCV giả lập"""
    base_price = 50000.0
    now = datetime.utcnow()
    data = []

    for i in range(n):
        ts = int((now - timedelta(minutes=(n - i) * 15)).timestamp() * 1000)
        if trend == "up":
            close = base_price + i * 10 + np.random.uniform(-5, 5)
        elif trend == "down":
            close = base_price - i * 10 + np.random.uniform(-5, 5)
        else:
            close = base_price + np.random.uniform(-200, 200)

        open_ = close + np.random.uniform(-50, 50)
        high = max(open_, close) + np.random.uniform(0, 100)
        low = min(open_, close) - np.random.uniform(0, 100)
        volume = np.random.uniform(100, 500)

        data.append([ts, open_, high, low, close, volume])

    return data


@pytest.fixture
def ohlcv_up():
    return make_ohlcv(200, "up")


@pytest.fixture
def ohlcv_down():
    return make_ohlcv(200, "down")


@pytest.fixture
def strategy_config():
    return {
        "ma_fast": 12,
        "ma_slow": 26,
        "ma_type": "EMA",
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "require_both_signals": False,  # Dễ trigger hơn cho test
        "check_interval_seconds": 60,
    }


# ─── Tests: Indicators ────────────────────────────────────────────────

class TestIndicators:

    def test_ohlcv_to_dataframe(self, ohlcv_up):
        df = ohlcv_to_dataframe(ohlcv_up)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 200
        assert all(col in df.columns for col in ["open", "high", "low", "close", "volume"])
        assert df.index.name == "timestamp"

    def test_ema_calculation(self, ohlcv_up):
        df = ohlcv_to_dataframe(ohlcv_up)
        ema = calculate_ema(df["close"], 12)
        assert len(ema) == len(df)
        # EMA không có NaN sau warm-up period
        assert not ema.iloc[-1:].isna().any()

    def test_macd_calculation(self, ohlcv_up):
        df = ohlcv_to_dataframe(ohlcv_up)
        macd, signal, hist = calculate_macd(df["close"])
        assert len(macd) == len(df)
        # Histogram = MACD - Signal
        last_hist = macd.iloc[-1] - signal.iloc[-1]
        assert abs(last_hist - hist.iloc[-1]) < 1e-10

    def test_get_ma_values(self, ohlcv_up):
        df = ohlcv_to_dataframe(ohlcv_up)
        ma = get_ma_values(df, fast_period=12, slow_period=26)
        assert ma is not None
        assert ma.fast > 0
        assert ma.slow > 0

    def test_ma_values_uptrend(self, ohlcv_up):
        """Trong uptrend, Fast MA nên > Slow MA"""
        df = ohlcv_to_dataframe(ohlcv_up)
        ma = get_ma_values(df, fast_period=12, slow_period=26)
        assert ma is not None
        assert ma.fast > ma.slow, "Trong uptrend, Fast MA phải > Slow MA"

    def test_ma_values_downtrend(self, ohlcv_down):
        """Trong downtrend, Fast MA nên < Slow MA"""
        df = ohlcv_to_dataframe(ohlcv_down)
        ma = get_ma_values(df, fast_period=12, slow_period=26)
        assert ma is not None
        assert ma.fast < ma.slow, "Trong downtrend, Fast MA phải < Slow MA"

    def test_get_macd_values(self, ohlcv_up):
        df = ohlcv_to_dataframe(ohlcv_up)
        macd = get_macd_values(df)
        assert macd is not None
        # Histogram = MACD - Signal
        assert abs((macd.macd - macd.signal) - macd.histogram) < 1e-10

    def test_insufficient_data(self):
        """Test với dữ liệu không đủ"""
        short_ohlcv = make_ohlcv(10)
        df = ohlcv_to_dataframe(short_ohlcv)
        result = get_ma_values(df, fast_period=12, slow_period=26)
        assert result is None

    def test_golden_cross_detection(self):
        """Test phát hiện Golden Cross"""
        from src.data.indicators import MAValues
        ma = MAValues(fast=100.0, slow=98.0, fast_prev=97.0, slow_prev=99.0)
        assert ma.golden_cross, "Phải phát hiện Golden Cross"
        assert not ma.death_cross

    def test_death_cross_detection(self):
        """Test phát hiện Death Cross"""
        from src.data.indicators import MAValues
        ma = MAValues(fast=98.0, slow=100.0, fast_prev=101.0, slow_prev=99.0)
        assert ma.death_cross, "Phải phát hiện Death Cross"
        assert not ma.golden_cross

    def test_macd_bullish_cross(self):
        """Test MACD bullish cross"""
        from src.data.indicators import MACDValues
        macd = MACDValues(macd=0.5, signal=0.2, histogram=0.3, macd_prev=-0.1, signal_prev=0.2)
        assert macd.bullish_cross, "Phải phát hiện MACD bullish cross"
        assert macd.is_positive


# ─── Tests: Strategy ──────────────────────────────────────────────────

class TestMaMacdStrategy:

    @pytest.mark.asyncio
    async def test_analyze_returns_signal(self, ohlcv_up, strategy_config):
        strategy = MaMacdStrategy(strategy_config)
        signal = await strategy.analyze("BTCUSDT", ohlcv_up, [])
        assert isinstance(signal, StrategySignal)
        assert signal.symbol == "BTCUSDT"
        assert signal.signal in ("long", "short", "close_long", "close_short", "none")

    @pytest.mark.asyncio
    async def test_insufficient_data(self, strategy_config):
        strategy = MaMacdStrategy(strategy_config)
        short_data = make_ohlcv(10)
        signal = await strategy.analyze("BTCUSDT", short_data, [])
        assert signal.signal == "none"
        assert "đủ" in signal.reason.lower() or "data" in signal.reason.lower()

    @pytest.mark.asyncio
    async def test_no_entry_when_position_open(self, ohlcv_up, strategy_config):
        """Không mở lệnh mới khi đã có vị thế"""
        strategy = MaMacdStrategy(strategy_config)
        existing_position = [{"symbol": "BTCUSDT", "side": "long", "size": 0.1}]
        signal = await strategy.analyze("BTCUSDT", ohlcv_up, existing_position)
        assert signal.signal != "long", "Không được mở Long khi đã có vị thế"

    @pytest.mark.asyncio
    async def test_signal_confidence(self, ohlcv_up, strategy_config):
        """Confidence phải trong khoảng 0-1"""
        strategy = MaMacdStrategy(strategy_config)
        signal = await strategy.analyze("BTCUSDT", ohlcv_up, [])
        assert 0.0 <= signal.confidence <= 1.0


# ─── Tests: Risk Manager ──────────────────────────────────────────────

class TestRiskManager:

    def test_position_calculation(self):
        from src.core.risk_manager import RiskManager
        rm = RiskManager({
            "leverage": 5,
            "position_size_pct": 0.10,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.04,
        })

        plan = rm.calculate_position(
            balance_usdt=1000.0,
            entry_price=50000.0,
            side="buy",
            symbol="BTCUSDT",
        )

        assert plan is not None
        assert plan.leverage == 5
        assert plan.stop_loss < plan.entry_price  # SL phải dưới entry cho Long
        assert plan.take_profit > plan.entry_price  # TP phải trên entry cho Long

    def test_sl_calculation_long(self):
        from src.core.risk_manager import RiskManager
        rm = RiskManager({"stop_loss_pct": 0.02, "take_profit_pct": 0.04,
                          "leverage": 1, "position_size_pct": 0.1})
        sl, tp = rm._calculate_sl_tp(50000, "buy")
        assert sl == pytest.approx(49000.0, rel=1e-6)
        assert tp == pytest.approx(52000.0, rel=1e-6)

    def test_sl_calculation_short(self):
        from src.core.risk_manager import RiskManager
        rm = RiskManager({"stop_loss_pct": 0.02, "take_profit_pct": 0.04,
                          "leverage": 1, "position_size_pct": 0.1})
        sl, tp = rm._calculate_sl_tp(50000, "sell")
        assert sl == pytest.approx(51000.0, rel=1e-6)
        assert tp == pytest.approx(48000.0, rel=1e-6)

    def test_max_positions_check(self):
        from src.core.risk_manager import RiskManager
        rm = RiskManager({"max_open_positions": 2, "leverage": 5,
                          "position_size_pct": 0.1, "stop_loss_pct": 0.02,
                          "take_profit_pct": 0.04})
        assert rm.check_max_positions([]) is True
        assert rm.check_max_positions([{}, {}]) is False

    def test_insufficient_balance(self):
        from src.core.risk_manager import RiskManager
        rm = RiskManager({"leverage": 5, "position_size_pct": 0.1,
                          "stop_loss_pct": 0.02, "take_profit_pct": 0.04})
        plan = rm.calculate_position(balance_usdt=0, entry_price=50000, side="buy", symbol="BTCUSDT")
        assert plan is None
