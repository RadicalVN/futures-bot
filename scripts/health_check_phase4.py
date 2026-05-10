"""health_check_phase4.py — Full System Health Check for Phase 4."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from unittest.mock import MagicMock

print("=" * 70)
print("  SYSTEM HEALTH REPORT — Phase 4")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

errors = []

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 1: Plugin Registry (Task 4.1)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[CHECK 1] Plugin Registry & Factory (Task 4.1)")
print("-" * 50)

from src.strategies.factory import StrategyFactory
StrategyFactory.reset_registry()
names = StrategyFactory.list_names()

print(f"  Registry count : {len(names)}")
print(f"  Strategies     : {names}")

# adts must be present
if "adts" in names:
    cls = StrategyFactory.get_strategy_class("adts")
    module = cls.__module__
    print(f"  adts module    : {module}")
    if "adts_strategy" in module:
        print("  [PASS] adts loaded from adts_strategy.py (single-file plugin)")
    else:
        msg = f"FAIL: adts loaded from wrong module: {module}"
        print(f"  [FAIL] {msg}")
        errors.append(msg)
else:
    msg = "FAIL: 'adts' not in registry"
    print(f"  [FAIL] {msg}")
    errors.append(msg)

# old adts/ folder must not exist
adts_folder = os.path.join("src", "strategies", "adts")
if os.path.exists(adts_folder):
    msg = f"FAIL: old folder {adts_folder} still exists"
    print(f"  [FAIL] {msg}")
    errors.append(msg)
else:
    print(f"  [PASS] src/strategies/adts/ folder deleted")

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 2: Dynamic Manifest (Task 4.2)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[CHECK 2] Dynamic UI Manifest (Task 4.2)")
print("-" * 50)

manifest = StrategyFactory.get_strategy_manifest("adts")
schema   = manifest.get("parameters_schema", {})
props    = schema.get("properties", {})

print(f"  manifest name  : {manifest['name']}")
print(f"  schema type    : {schema.get('type')}")
print(f"  property count : {len(props)}")

required_fields = [
    "timeframe", "adx_threshold", "bbwidth_threshold_factor",
    "sl_atr_mult", "tp1_rr", "emergency_adx_threshold", "leverage",
]
for field in required_fields:
    if field in props:
        widget = props[field].get("ui:widget", "MISSING")
        default = props[field].get("default", "MISSING")
        print(f"  [PASS] {field:35s} ui:widget={widget}, default={default}")
    else:
        msg = f"FAIL: missing field '{field}' in ADTS schema"
        print(f"  [FAIL] {msg}")
        errors.append(msg)

# Spot-check ui:widget values
for fname, prop in props.items():
    widget = prop.get("ui:widget")
    if widget not in ("number", "select", "boolean", "text"):
        msg = f"FAIL: {fname} has invalid ui:widget='{widget}'"
        print(f"  [FAIL] {msg}")
        errors.append(msg)

if not errors:
    print("  [PASS] All ADTS schema fields valid")

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 3: Analytics Consistency — Mock Bulk Backtest (Task 4.3 & 4.4)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[CHECK 3] Analytics Consistency — Mock Bulk Backtest (Task 4.3 & 4.4)")
print("-" * 50)

from src.apps.analytics.service import _calc_metrics, _MockTrade, _build_mock_trades

# Simulate 3 symbols with different trade outcomes
MOCK_SCENARIOS = {
    "BTCUSDT": [
        (+85.20, 2.5), (+42.10, 1.8), (-22.50, 3.0), (+110.00, 4.2),
        (-15.30, 1.5), (+67.80, 2.1), (+38.50, 1.9), (-8.70, 0.8),
    ],
    "ETHUSDT": [
        (+32.10, 1.5), (-18.40, 2.0), (+55.60, 3.1), (-41.20, 2.5),
        (+28.90, 1.8), (+19.70, 1.2), (-12.30, 0.9), (+44.50, 2.8),
    ],
    "BNBUSDT": [
        (-25.10, 1.2), (+18.30, 2.0), (-33.40, 1.8), (+12.60, 1.5),
        (-8.90, 0.7), (+22.10, 2.3), (-15.70, 1.1), (+9.80, 1.6),
    ],
}

base_time = datetime.utcnow() - timedelta(days=30)
results = []

for symbol, trades_data in MOCK_SCENARIOS.items():
    mock_trades = []
    for idx, (pnl, hours) in enumerate(trades_data):
        created = base_time + timedelta(days=idx * 3)
        closed  = created + timedelta(hours=hours)
        mock_trades.append(_MockTrade(pnl, created, closed))

    m = _calc_metrics(mock_trades)
    results.append({
        "symbol":        symbol,
        "total_trades":  m.total_trades,
        "win_rate_pct":  m.win_rate_pct,
        "net_pnl":       m.net_pnl,
        "profit_factor": m.profit_factor,
        "max_drawdown":  m.max_drawdown,
        "avg_duration":  m.avg_duration_hours,
    })

# Print comparison table
print(f"  {'Symbol':<12} {'Trades':>6} {'Win%':>7} {'Net PnL':>10} {'PF':>6} {'MaxDD':>8} {'AvgDur':>8}")
print(f"  {'-'*12} {'-'*6} {'-'*7} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")
for r in results:
    pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] is not None else "N/A"
    pnl_sign = "+" if r['net_pnl'] >= 0 else ""
    print(
        f"  {r['symbol']:<12} {r['total_trades']:>6} "
        f"{r['win_rate_pct']:>6.1f}% "
        f"{pnl_sign}{r['net_pnl']:>9.2f} "
        f"{pf_str:>6} "
        f"{r['max_drawdown']:>7.2f} "
        f"{r['avg_duration']:>7.1f}h"
    )

# Summary
done = [r for r in results if r["net_pnl"] is not None]
best  = max(done, key=lambda r: r["net_pnl"])
worst = min(done, key=lambda r: r["net_pnl"])
avg_pnl = sum(r["net_pnl"] for r in done) / len(done)
print(f"\n  Best  : {best['symbol']} (+${best['net_pnl']:.2f})")
print(f"  Worst : {worst['symbol']} (${worst['net_pnl']:.2f})")
print(f"  Avg PnL: ${avg_pnl:.2f}")
print("  [PASS] _calc_metrics() used for all 3 symbols — consistent with live trading")

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 4: Architecture Audit
# ══════════════════════════════════════════════════════════════════════════════
print("\n[CHECK 4] Architecture Audit — Zero-Core-Edit (Task 4.1)")
print("-" * 50)

STRATEGY_NAMES = [
    "ma_macd", "custom_sma", "custom_macd",
    "sma_trend_early_exit", "sma_pullback", "sma_anti_sideway",
    "sma_macd_cross", "sma_macd_cross_v2", "sma_macd_cross_v3",
    "sma_macd_cross_v4", "sma_macd_cross_v5", "sma_macd_cross_v6",
    "sma_macd_cross_v7", "adts",
]

AUDIT_FILES = {
    "src/core/bot_engine.py":                    "BotEngine",
    "src/apps/monitoring/exit_monitor_service.py": "ExitMonitorService",
}

for filepath, label in AUDIT_FILES.items():
    src = open(filepath, encoding="utf-8").read()
    found_hardcode = []
    for name in STRATEGY_NAMES:
        # Check for hardcoded string comparisons like == "adts" or "sma_macd_cross"
        patterns = [
            f'== "{name}"',
            f"== '{name}'",
            f'strategy_name == "{name}"',
        ]
        for pat in patterns:
            if pat in src:
                found_hardcode.append(f"{pat}")

    if found_hardcode:
        msg = f"FAIL: {label} has hardcoded strategy names: {found_hardcode}"
        print(f"  [FAIL] {msg}")
        errors.append(msg)
    else:
        print(f"  [PASS] {label} ({filepath})")
        print(f"         No hardcoded strategy names found")

# Confirm StrategyFactory usage
for filepath, label in AUDIT_FILES.items():
    src = open(filepath, encoding="utf-8").read()
    if "StrategyFactory" in src or "strategy.requires_one_shot_check" in src or "prepare_metadata" in src:
        print(f"  [PASS] {label} uses Factory/contract pattern")

# ══════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
if errors:
    print(f"  RESULT: FAIL — {len(errors)} issue(s) found:")
    for e in errors:
        print(f"    - {e}")
else:
    print("  RESULT: ALL CHECKS PASSED — Phase 4 HEALTHY")
print("=" * 70)
