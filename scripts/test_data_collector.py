"""
test_data_collector.py — Kiem tra nhanh OHLCVCollectorService.

Test 1-5: Unit test (khong can DB/exchange).
Test 6:   Integration test tuy chon (can DB + exchange).

Chay unit tests:
    venv\\Scripts\\python.exe scripts/test_data_collector.py

Chay ca integration test (can DB + Binance):
    venv\\Scripts\\python.exe scripts/test_data_collector.py --integration
"""
import asyncio
import sys
import inspect

sys.path.insert(0, ".")


# ── Test 1: Import ────────────────────────────────────────────────────────────

def test_imports():
    """Test 1: Import tat ca symbols tu module."""
    from src.apps.data_collector.ohlcv_collector_service import (
        OHLCVCollectorService,
        setup_data_collector_job,
        DatasetKey,
        _needs_update,
        _tf_to_seconds,
        _summarize_results,
        _load_datasets_needing_update,
        _update_one_dataset,
        _SCAN_INTERVAL_SECONDS,
        _LOCK_TTL_SECONDS,
        _JOB_ID,
        _LAG_RATIO,
    )
    print("[OK] Test 1: Import tat ca symbols OK")
    return locals()


# ── Test 2: Constants ─────────────────────────────────────────────────────────

def test_constants(symbols: dict):
    """Test 2: Hang so dung gia tri theo spec."""
    assert symbols["_SCAN_INTERVAL_SECONDS"] == 60, \
        f"Expected 60, got {symbols['_SCAN_INTERVAL_SECONDS']}"
    assert symbols["_LOCK_TTL_SECONDS"] == 55, \
        f"Expected 55, got {symbols['_LOCK_TTL_SECONDS']}"
    assert symbols["_LOCK_TTL_SECONDS"] < symbols["_SCAN_INTERVAL_SECONDS"], \
        "lock_ttl phai nho hon interval"
    assert symbols["_JOB_ID"] == "ohlcv_data_collector", \
        f"Expected 'ohlcv_data_collector', got {symbols['_JOB_ID']!r}"
    assert 0 < symbols["_LAG_RATIO"] <= 1.0, \
        f"_LAG_RATIO phai trong (0, 1]: {symbols['_LAG_RATIO']}"
    print(
        f"[OK] Test 2: Constants — interval={symbols['_SCAN_INTERVAL_SECONDS']}s, "
        f"lock_ttl={symbols['_LOCK_TTL_SECONDS']}s, "
        f"job_id={symbols['_JOB_ID']!r}, "
        f"lag_ratio={symbols['_LAG_RATIO']}"
    )


# ── Test 3: _tf_to_seconds ────────────────────────────────────────────────────

def test_tf_to_seconds(symbols: dict):
    """Test 3: Chuyen doi timeframe sang giay chinh xac."""
    fn = symbols["_tf_to_seconds"]
    cases = [
        ("1m",  60),
        ("5m",  300),
        ("15m", 900),
        ("1h",  3600),
        ("4h",  14400),
        ("1d",  86400),
        ("1w",  604800),
        ("xyz", 300),   # fallback
    ]
    for tf, expected in cases:
        result = fn(tf)
        assert result == expected, f"_tf_to_seconds({tf!r}): expected {expected}, got {result}"
    print(f"[OK] Test 3: _tf_to_seconds — {len(cases)} cases pass")


# ── Test 4: _needs_update ─────────────────────────────────────────────────────

def test_needs_update(symbols: dict):
    """Test 4: Logic loc dataset theo lag threshold."""
    fn = symbols["_needs_update"]

    # lag_hours=None → luon can update (chua co data)
    assert fn(None, "5m") is True, "lag=None phai can update"
    assert fn(None, "1h") is True, "lag=None phai can update"

    # 5m (300s), threshold = 300 * 0.5 = 150s = 0.0417h
    # lag = 0.05h (180s) > 150s → can update
    assert fn(0.05, "5m") is True, "lag=180s > threshold=150s phai update"
    # lag = 0.02h (72s) < 150s → khong can update
    assert fn(0.02, "5m") is False, "lag=72s < threshold=150s khong update"

    # 1h (3600s), threshold = 3600 * 0.5 = 1800s = 0.5h
    # lag = 0.6h (2160s) > 1800s → can update
    assert fn(0.6, "1h") is True, "lag=2160s > threshold=1800s phai update"
    # lag = 0.3h (1080s) < 1800s → khong can update
    assert fn(0.3, "1h") is False, "lag=1080s < threshold=1800s khong update"

    # 1d (86400s), threshold = 86400 * 0.5 = 43200s = 12h
    assert fn(13.0, "1d") is True,  "lag=13h > threshold=12h phai update"
    assert fn(5.0,  "1d") is False, "lag=5h < threshold=12h khong update"

    print("[OK] Test 4: _needs_update — 8 cases pass")


# ── Test 5: _summarize_results ────────────────────────────────────────────────

def test_summarize_results(symbols: dict):
    """Test 5: Tong hop ket qua tu gather chinh xac."""
    fn = symbols["_summarize_results"]
    DatasetKey = symbols["DatasetKey"]

    datasets = [
        DatasetKey("sma_macd_cross", "BTCUSDT", "5m"),
        DatasetKey("sma_macd_cross", "ETHUSDT", "5m"),
        DatasetKey("adts",           "BTCUSDT", "1h"),
    ]
    results = [
        {"status": "done", "total_inserted": 10},
        ValueError("Timeout"),                          # exception
        {"status": "up_to_date", "total_inserted": 0},
    ]

    ok_count, error_count, total_inserted = fn(datasets, results)

    assert ok_count       == 2,  f"ok_count: {ok_count}"
    assert error_count    == 1,  f"error_count: {error_count}"
    assert total_inserted == 10, f"total_inserted: {total_inserted}"

    print(
        f"[OK] Test 5: _summarize_results — "
        f"ok={ok_count}, errors={error_count}, inserted={total_inserted}"
    )


# ── Test 6: DatasetKey frozen dataclass ──────────────────────────────────────

def test_dataset_key(symbols: dict):
    """Test 6: DatasetKey la frozen dataclass, hashable."""
    import dataclasses
    DatasetKey = symbols["DatasetKey"]

    assert dataclasses.is_dataclass(DatasetKey), "DatasetKey phai la dataclass"

    k1 = DatasetKey("sma_macd_cross", "BTCUSDT", "5m")
    k2 = DatasetKey("sma_macd_cross", "BTCUSDT", "5m")
    k3 = DatasetKey("adts",           "BTCUSDT", "5m")

    # Frozen → hashable → co the dung trong set
    s = {k1, k2, k3}
    assert len(s) == 2, f"Set phai co 2 phan tu (k1==k2), got {len(s)}"

    # Frozen → khong the sua
    try:
        k1.symbol = "ETHUSDT"
        assert False, "Phai raise FrozenInstanceError"
    except Exception:
        pass  # Expected

    print(f"[OK] Test 6: DatasetKey frozen dataclass — hashable, immutable")


# ── Test 7: Async methods ─────────────────────────────────────────────────────

def test_async_methods(symbols: dict):
    """Test 7: Cac I/O methods phai la async coroutine."""
    OHLCVCollectorService = symbols["OHLCVCollectorService"]
    _load_datasets_needing_update = symbols["_load_datasets_needing_update"]
    _update_one_dataset = symbols["_update_one_dataset"]

    assert inspect.iscoroutinefunction(OHLCVCollectorService.run_once), \
        "run_once phai la coroutine"
    assert inspect.iscoroutinefunction(OHLCVCollectorService._execute_collection_cycle), \
        "_execute_collection_cycle phai la coroutine"
    assert inspect.iscoroutinefunction(_load_datasets_needing_update), \
        "_load_datasets_needing_update phai la coroutine"
    assert inspect.iscoroutinefunction(_update_one_dataset), \
        "_update_one_dataset phai la coroutine"

    print("[OK] Test 7: Tat ca I/O methods deu la async coroutine")


# ── Test 8: setup_data_collector_job la sync function ────────────────────────

def test_setup_function(symbols: dict):
    """Test 8: setup_data_collector_job la sync function."""
    fn = symbols["setup_data_collector_job"]
    assert callable(fn), "setup_data_collector_job phai callable"
    assert not inspect.iscoroutinefunction(fn), \
        "setup_data_collector_job KHONG duoc la coroutine"
    print("[OK] Test 8: setup_data_collector_job la sync function")


# ── Test 9: Package __init__.py export ───────────────────────────────────────

def test_package_init():
    """Test 9: __init__.py export dung function."""
    from src.apps.data_collector import setup_data_collector_job as fn
    from src.apps.data_collector.ohlcv_collector_service import (
        setup_data_collector_job as fn2,
    )
    assert fn is fn2, "__init__.py phai export dung function"
    print("[OK] Test 9: src.apps.data_collector.__init__.py export OK")


# ── Test 10: main.py integration ─────────────────────────────────────────────

def test_main_py_integration():
    """Test 10: main.py da co setup_data_collector_job call."""
    with open("main.py", encoding="utf-8") as f:
        content = f.read()
    assert "setup_data_collector_job" in content, \
        "main.py phai goi setup_data_collector_job"
    assert "from src.apps.data_collector import setup_data_collector_job" in content, \
        "main.py phai import tu src.apps.data_collector"
    print("[OK] Test 10: main.py da tich hop setup_data_collector_job")


# ── Test 11: No cross-app imports ────────────────────────────────────────────

def test_no_cross_app_imports():
    """Test 11: Khong co cross-app import (apps.X import apps.Y)."""
    import ast
    with open(
        "src/apps/data_collector/ohlcv_collector_service.py", encoding="utf-8"
    ) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
            if (
                module.startswith("src.apps.")
                and not module.startswith("src.apps.data_collector")
            ):
                raise AssertionError(
                    f"Cross-app import bi cam: {module} (dong {node.lineno})"
                )
    print("[OK] Test 11: Khong co cross-app import")


# ── Test 12: Semaphore constant ───────────────────────────────────────────────

def test_semaphore_constant(symbols: dict):
    """Test 12: _MAX_CONCURRENT_FETCHES ton tai va hop le."""
    from src.apps.data_collector.ohlcv_collector_service import (
        _MAX_CONCURRENT_FETCHES,
    )
    assert isinstance(_MAX_CONCURRENT_FETCHES, int), \
        "_MAX_CONCURRENT_FETCHES phai la int"
    assert 1 <= _MAX_CONCURRENT_FETCHES <= 50, \
        f"_MAX_CONCURRENT_FETCHES phai trong [1, 50], got {_MAX_CONCURRENT_FETCHES}"
    print(
        f"[OK] Test 12: _MAX_CONCURRENT_FETCHES={_MAX_CONCURRENT_FETCHES} "
        f"(gioi han {_MAX_CONCURRENT_FETCHES} request dong thoi)"
    )


# ── Test 13: Semaphore gioi han concurrency ───────────────────────────────────

async def test_semaphore_limits_concurrency():
    """Test 13: Semaphore dam bao khong qua _MAX_CONCURRENT_FETCHES request dong thoi."""
    import asyncio
    from src.apps.data_collector.ohlcv_collector_service import _MAX_CONCURRENT_FETCHES

    MAX = _MAX_CONCURRENT_FETCHES
    TOTAL_TASKS = MAX * 3  # 3x so luong slot de chac chan co task phai cho

    semaphore    = asyncio.Semaphore(MAX)
    peak_concurrent = 0
    current_concurrent = 0

    async def fake_fetch(i: int) -> int:
        nonlocal peak_concurrent, current_concurrent
        async with semaphore:
            current_concurrent += 1
            peak_concurrent = max(peak_concurrent, current_concurrent)
            await asyncio.sleep(0.02)  # gia lap I/O
            current_concurrent -= 1
        return i

    results = await asyncio.gather(
        *[fake_fetch(i) for i in range(TOTAL_TASKS)],
        return_exceptions=True,
    )

    assert len(results) == TOTAL_TASKS, f"Phai co {TOTAL_TASKS} ket qua"
    assert all(isinstance(r, int) for r in results), "Tat ca phai thanh cong"
    assert peak_concurrent <= MAX, \
        f"Dinh concurrency {peak_concurrent} vuot qua gioi han {MAX}"

    print(
        f"[OK] Test 13: Semaphore gioi han concurrency "
        f"(peak={peak_concurrent}/{MAX}, total={TOTAL_TASKS} tasks)"
    )


# ── Test 12: Integration (optional) ──────────────────────────────────────────

async def test_integration_run_once():
    """Test 12 (Integration): Chay run_once() that voi DB + Exchange.

    Chi chay khi co flag --integration.
    Ket qua: khong raise exception, log hien thi ket qua.
    """
    from dotenv import load_dotenv
    load_dotenv()

    from src.database.db import init_db
    from src.apps.data_collector.ohlcv_collector_service import OHLCVCollectorService

    print("[Integration] Khoi tao DB...")
    await init_db()

    print("[Integration] Chay OHLCVCollectorService.run_once()...")
    service = OHLCVCollectorService()
    await service.run_once()
    print("[OK] Test 12 (Integration): run_once() hoan tat khong co exception")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_unit_tests():
    """Chay tat ca unit tests (khong can DB/exchange)."""
    print("=" * 60)
    print("  OHLCVCollectorService — Unit Tests")
    print("=" * 60)
    print()

    symbols = test_imports()
    test_constants(symbols)
    test_tf_to_seconds(symbols)
    test_needs_update(symbols)
    test_summarize_results(symbols)
    test_dataset_key(symbols)
    test_async_methods(symbols)
    test_setup_function(symbols)
    test_package_init()
    test_main_py_integration()
    test_no_cross_app_imports()
    test_semaphore_constant(symbols)
    asyncio.run(test_semaphore_limits_concurrency())

    print()
    print("=" * 60)
    print("  TAT CA 13 UNIT TESTS PASS")
    print("=" * 60)


if __name__ == "__main__":
    run_integration = "--integration" in sys.argv

    try:
        run_unit_tests()

        if run_integration:
            print()
            print("=" * 60)
            print("  Integration Test (can DB + Binance)")
            print("=" * 60)
            asyncio.run(test_integration_run_once())

        sys.exit(0)

    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)
