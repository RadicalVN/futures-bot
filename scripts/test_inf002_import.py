"""Quick import check for INF-002 refactor."""
import sys
sys.path.insert(0, ".")

from src.dashboard.routers.backtest import (
    router,
    _run_engine_job,
    _map_result_to_legacy,
    _validate_db_range,
    _validate_candle_count,
    _calc_mdd_details,
    _calc_mdd_recovery,
    _run_job,
    _run_job_strategy,
    _run_single_bulk,
    BacktestConfig,
    BacktestEngine,
)

print("Import OK")
print(f"_run_engine_job: {_run_engine_job.__name__}")
print(f"_map_result_to_legacy: {_map_result_to_legacy.__name__}")
print(f"BacktestEngine: {BacktestEngine.__name__}")

# Verify _run_backtest_engine is gone (dead code still exists but not called)
import inspect
src = inspect.getsource(_run_job)
assert "_run_backtest_engine" not in src, "_run_job still calls legacy engine!"
assert "_run_engine_job" in src, "_run_job must call new engine!"
print("_run_job uses new engine: OK")

src2 = inspect.getsource(_run_job_strategy)
assert "_run_backtest_engine" not in src2, "_run_job_strategy still calls legacy engine!"
assert "_run_engine_job" in src2, "_run_job_strategy must call new engine!"
print("_run_job_strategy uses new engine: OK")

src3 = inspect.getsource(_run_single_bulk)
assert "_poll_job_until_done" not in src3, "_run_single_bulk still uses polling!"
assert "_run_engine_job" in src3, "_run_single_bulk must call engine directly!"
print("_run_single_bulk uses engine directly (no polling): OK")

# Verify _calc_mdd_details returns correct tuple
vals = [10000.0, 10100.0, 9900.0, 10200.0, 9800.0]
ts   = [1000, 2000, 3000, 4000, 5000]
mdd_pct, mdd_usdt, pk_ts, tr_ts, pk_val, tr_val = _calc_mdd_details(vals, ts, 10000.0)
assert mdd_pct > 0, "MDD must be > 0"
assert tr_val < pk_val, "Trough must be below peak"
print(f"_calc_mdd_details: mdd_pct={mdd_pct}%, peak={pk_val}, trough={tr_val}: OK")

print("\nAll checks PASSED")
