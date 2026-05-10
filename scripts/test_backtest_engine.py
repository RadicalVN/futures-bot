"""
test_backtest_engine.py — Kiểm thử BacktestEngine và analytics.py.

Mô phỏng 3 kịch bản:
  1. Analytics math: calc_trade_metrics, MDD, Sharpe
  2. BacktestEngine: khởi tạo, normalize input, resolve range
  3. VirtualPosition: to_exchange_format, partial close state

Chạy: venv\Scripts\python.exe scripts/test_backtest_engine.py
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.core.analytics import (
    TradeMetrics,
    calc_trade_metrics,
    calc_max_drawdown_from_pnl,
    calc_max_drawdown_from_equity,
    calc_sharpe_ratio,
)
from src.core.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    VirtualPosition,
    TradeRecord,
)


# ── Test 1: Analytics math ────────────────────────────────────────────────────

async def test_analytics_math() -> None:
    print("\n" + "="*60)
    print("TEST 1: Analytics math — calc_trade_metrics")
    print("="*60)

    pnl_list   = [100.0, -50.0, 200.0, -30.0, 80.0]
    durations  = [2.0, 1.5, 3.0, 0.5, 2.5]
    commissions = [1.0, 0.5, 2.0, 0.3, 0.8]

    metrics = calc_trade_metrics(pnl_list, durations, commissions)

    assert metrics.total_trades == 5
    assert metrics.winning_trades == 3
    assert metrics.losing_trades == 2
    assert abs(metrics.win_rate_pct - 60.0) < 0.01
    assert abs(metrics.net_pnl - 300.0) < 0.01
    assert abs(metrics.gross_profit - 380.0) < 0.01
    assert abs(metrics.gross_loss - 80.0) < 0.01
    assert metrics.profit_factor is not None
    assert abs(metrics.profit_factor - 4.75) < 0.01
    assert abs(metrics.total_commission - 4.6) < 0.01
    print(f"  ✅ total_trades={metrics.total_trades}, win_rate={metrics.win_rate_pct}%")
    print(f"  ✅ net_pnl={metrics.net_pnl}, profit_factor={metrics.profit_factor}")
    print(f"  ✅ total_commission={metrics.total_commission}")
    print("  → PASS")


async def test_max_drawdown() -> None:
    print("\n" + "="*60)
    print("TEST 2: Max Drawdown calculation")
    print("="*60)

    # Equity: 0 → 100 → 50 → 150 → 80 → 200
    # Peak: 0 → 100 → 100 → 150 → 150 → 200
    # DD:   0 → 0   → 50  → 0   → 70  → 0
    # MDD = 70
    pnl_list = [100.0, -50.0, 100.0, -70.0, 120.0]
    mdd = calc_max_drawdown_from_pnl(pnl_list)
    assert abs(mdd - 70.0) < 0.01, f"MDD={mdd}, expected=70.0"
    print(f"  ✅ MDD from PnL list = {mdd} (expected 70.0)")

    equity_curve = [10000.0, 10100.0, 10050.0, 10150.0, 10080.0, 10200.0]
    mdd_eq = calc_max_drawdown_from_equity(equity_curve)
    assert abs(mdd_eq - 70.0) < 0.01, f"MDD_eq={mdd_eq}, expected=70.0"
    print(f"  ✅ MDD from equity curve = {mdd_eq} (expected 70.0)")
    print("  → PASS")


async def test_sharpe_ratio() -> None:
    print("\n" + "="*60)
    print("TEST 3: Sharpe Ratio")
    print("="*60)

    # Sharpe = None khi < 2 phần tử
    assert calc_sharpe_ratio([1.0]) is None
    assert calc_sharpe_ratio([]) is None
    print("  ✅ Sharpe = None khi < 2 phần tử")

    # Sharpe = None khi std = 0 (tất cả returns bằng nhau)
    assert calc_sharpe_ratio([1.0, 1.0, 1.0]) is None
    print("  ✅ Sharpe = None khi std = 0")

    # Sharpe hợp lệ
    returns = [1.0, 2.0, -1.0, 3.0, 0.5, 1.5]
    sharpe = calc_sharpe_ratio(returns)
    assert sharpe is not None
    assert sharpe > 0
    print(f"  ✅ Sharpe = {sharpe} (> 0)")
    print("  → PASS")


# ── Test 4: BacktestEngine init ───────────────────────────────────────────────

async def test_engine_init() -> None:
    print("\n" + "="*60)
    print("TEST 4: BacktestEngine init và normalize input")
    print("="*60)

    config = BacktestConfig(
        strategy_name="ma_macd",
        parameters={"leverage": 5, "position_size_pct": 0.1},
        symbol="BTC/USDT",
        initial_balance=10000.0,
    )
    engine = BacktestEngine(config)
    assert engine._config.strategy_name == "ma_macd"
    assert engine._lookback >= 200
    print(f"  ✅ Engine init: strategy=ma_macd, lookback={engine._lookback}")

    # Test normalize list input
    candles = [[i * 300000, 100.0, 101.0, 99.0, 100.5, 1000.0] for i in range(10)]
    normalized = BacktestEngine._normalize_input(candles)
    assert normalized == candles
    print(f"  ✅ normalize list input: {len(normalized)} candles")

    # Test normalize DataFrame input
    import pandas as pd
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    normalized_df = BacktestEngine._normalize_input(df)
    assert len(normalized_df) == 10
    assert normalized_df[0][4] == 100.5  # close
    print(f"  ✅ normalize DataFrame input: {len(normalized_df)} candles")
    print("  → PASS")


# ── Test 5: VirtualPosition ───────────────────────────────────────────────────

async def test_virtual_position() -> None:
    print("\n" + "="*60)
    print("TEST 5: VirtualPosition — to_exchange_format và ADTS fields")
    print("="*60)

    pos = VirtualPosition(
        symbol="BTC/USDT",
        side="long",
        entry_price=95000.0,
        amount=0.01,
        amount_total=0.01,
        position_value=950.0,
        stop_loss=93575.0,
        take_profit=96710.0,
        opened_at=1000000,
        tp1_hit=False,
        sl_moved_to_entry=False,
        emergency_triggered=False,
    )

    fmt = pos.to_exchange_format()
    assert fmt["symbol"] == "BTC/USDT"
    assert fmt["side"] == "long"
    assert fmt["contracts"] == 0.01
    assert fmt["size"] == 0.01
    assert fmt["entry_price"] == 95000.0
    print(f"  ✅ to_exchange_format: symbol={fmt['symbol']}, side={fmt['side']}, contracts={fmt['contracts']}")

    # Test ADTS state fields
    pos.tp1_hit = True
    pos.sl_moved_to_entry = True
    pos.emergency_triggered = True
    assert pos.tp1_hit is True
    assert pos.sl_moved_to_entry is True
    assert pos.emergency_triggered is True
    print(f"  ✅ ADTS fields: tp1_hit={pos.tp1_hit}, sl_moved={pos.sl_moved_to_entry}, emergency={pos.emergency_triggered}")
    print("  → PASS")


# ── Test 6: TradeRecord duration ──────────────────────────────────────────────

async def test_trade_record_duration() -> None:
    print("\n" + "="*60)
    print("TEST 6: TradeRecord duration_hours")
    print("="*60)

    trade = TradeRecord(
        entry_ts=0,
        exit_ts=3_600_000 * 2,  # 2 giờ
        side="long",
        entry_price=95000.0,
        exit_price=96000.0,
        amount=0.01,
        pnl_gross=10.0,
        commission=0.1,
        pnl_net=9.9,
        reason="TP1",
        is_partial=True,
    )
    assert abs(trade.duration_hours - 2.0) < 0.001
    print(f"  ✅ duration_hours = {trade.duration_hours} (expected 2.0)")
    print("  → PASS")


# ── Test 7: BacktestEngine _calc_trade_record ─────────────────────────────────

async def test_calc_trade_record() -> None:
    print("\n" + "="*60)
    print("TEST 7: BacktestEngine._calc_trade_record — PnL accuracy")
    print("="*60)

    config = BacktestConfig(
        strategy_name="ma_macd",
        parameters={},
        commission_pct=0.0005,
    )
    engine = BacktestEngine(config)

    pos = VirtualPosition(
        symbol="BTC/USDT", side="long",
        entry_price=95000.0, amount=0.01, amount_total=0.01,
        position_value=950.0, stop_loss=0.0, take_profit=0.0, opened_at=0,
    )

    # LONG: exit 96000 → pnl_gross = (96000 - 95000) * 0.01 = 10.0
    # commission = (95000 * 0.01 + 96000 * 0.01) * 0.0005 = 0.9550
    trade = engine._calc_trade_record(pos, 96000.0, 0.01, 1000, "TP1", False)
    assert abs(trade.pnl_gross - 10.0) < 0.001
    expected_comm = (95000 * 0.01 + 96000 * 0.01) * 0.0005
    assert abs(trade.commission - expected_comm) < 0.0001
    assert abs(trade.pnl_net - (10.0 - expected_comm)) < 0.0001
    print(f"  ✅ LONG pnl_gross={trade.pnl_gross}, commission={trade.commission:.4f}, pnl_net={trade.pnl_net:.4f}")

    # SHORT: exit 94000 → pnl_gross = (95000 - 94000) * 0.01 = 10.0
    pos_short = VirtualPosition(
        symbol="BTC/USDT", side="short",
        entry_price=95000.0, amount=0.01, amount_total=0.01,
        position_value=950.0, stop_loss=0.0, take_profit=0.0, opened_at=0,
    )
    trade_s = engine._calc_trade_record(pos_short, 94000.0, 0.01, 1000, "TP1", False)
    assert abs(trade_s.pnl_gross - 10.0) < 0.001
    print(f"  ✅ SHORT pnl_gross={trade_s.pnl_gross}")
    print("  → PASS")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n🧪 BacktestEngine + Analytics — Test Suite")
    print("=" * 60)

    await test_analytics_math()
    await test_max_drawdown()
    await test_sharpe_ratio()
    await test_engine_init()
    await test_virtual_position()
    await test_trade_record_duration()
    await test_calc_trade_record()

    print("\n" + "="*60)
    print("✅ Tất cả 7 tests PASSED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
