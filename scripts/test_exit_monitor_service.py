"""
test_exit_monitor_service.py — Kiểm tra nhanh ExitMonitorService.

Chay: venv\\Scripts\\python.exe scripts/test_exit_monitor_service.py
"""
import sys
import inspect

sys.path.insert(0, ".")


def test_imports():
    """Test 1: Import tất cả symbols từ module."""
    from src.apps.monitoring.exit_monitor_service import (
        ExitMonitorService,
        setup_exit_monitor_job,
        _ExchangeCache,
        _build_strategy,
        _check_and_close_trade,
        _execute_close,
        _fetch_exit_meta,
        _update_trade_closed,
        _update_bot_stats,
        _SCAN_INTERVAL_SECONDS,
        _LOCK_TTL_SECONDS,
        _JOB_ID,
    )
    print("[OK] Test 1: Import exit_monitor_service — tat ca symbols OK")
    return locals()


def test_async_methods(symbols: dict):
    """Test 2: Tất cả I/O methods phải là async coroutine."""
    ExitMonitorService = symbols["ExitMonitorService"]
    assert inspect.iscoroutinefunction(ExitMonitorService.run_once), \
        "run_once phai la coroutine"
    assert inspect.iscoroutinefunction(ExitMonitorService._load_open_trades), \
        "_load_open_trades phai la coroutine"
    assert inspect.iscoroutinefunction(ExitMonitorService._process_trade), \
        "_process_trade phai la coroutine"
    assert inspect.iscoroutinefunction(symbols["_check_and_close_trade"]), \
        "_check_and_close_trade phai la coroutine"
    assert inspect.iscoroutinefunction(symbols["_execute_close"]), \
        "_execute_close phai la coroutine"
    assert inspect.iscoroutinefunction(symbols["_fetch_exit_meta"]), \
        "_fetch_exit_meta phai la coroutine"
    assert inspect.iscoroutinefunction(symbols["_update_trade_closed"]), \
        "_update_trade_closed phai la coroutine"
    assert inspect.iscoroutinefunction(symbols["_update_bot_stats"]), \
        "_update_bot_stats phai la coroutine"
    print("[OK] Test 2: Tat ca I/O methods deu la async coroutine")


def test_constants(symbols: dict):
    """Test 3: Hằng số đúng giá trị theo spec."""
    assert symbols["_SCAN_INTERVAL_SECONDS"] == 30, \
        f"Expected 30, got {symbols['_SCAN_INTERVAL_SECONDS']}"
    assert symbols["_LOCK_TTL_SECONDS"] == 25, \
        f"Expected 25, got {symbols['_LOCK_TTL_SECONDS']}"
    assert symbols["_LOCK_TTL_SECONDS"] < symbols["_SCAN_INTERVAL_SECONDS"], \
        "lock_ttl phai nho hon interval de tranh overlap"
    assert symbols["_JOB_ID"] == "exit_monitor_global", \
        f"Expected 'exit_monitor_global', got {symbols['_JOB_ID']!r}"
    print(
        f"[OK] Test 3: Constants — interval={symbols['_SCAN_INTERVAL_SECONDS']}s, "
        f"lock_ttl={symbols['_LOCK_TTL_SECONDS']}s, "
        f"job_id={symbols['_JOB_ID']!r}"
    )


def test_exchange_cache(symbols: dict):
    """Test 4: _ExchangeCache interface đầy đủ."""
    _ExchangeCache = symbols["_ExchangeCache"]
    cache = _ExchangeCache()
    assert hasattr(cache, "get_or_create"), "Missing get_or_create"
    assert hasattr(cache, "close_all"), "Missing close_all"
    assert inspect.iscoroutinefunction(cache.get_or_create), \
        "get_or_create phai la coroutine"
    assert inspect.iscoroutinefunction(cache.close_all), \
        "close_all phai la coroutine"
    assert cache._cache == {}, "Cache phai khoi tao rong"
    print("[OK] Test 4: _ExchangeCache interface OK")


def test_setup_function(symbols: dict):
    """Test 5: setup_exit_monitor_job là sync function (không phải coroutine)."""
    fn = symbols["setup_exit_monitor_job"]
    assert callable(fn), "setup_exit_monitor_job phai callable"
    assert not inspect.iscoroutinefunction(fn), \
        "setup_exit_monitor_job KHONG duoc la coroutine (chi dang ky job, khong await)"
    print("[OK] Test 5: setup_exit_monitor_job la sync function")


def test_package_init():
    """Test 6: __init__.py export đúng function."""
    from src.apps.monitoring import setup_exit_monitor_job as fn
    from src.apps.monitoring.exit_monitor_service import setup_exit_monitor_job as fn2
    assert fn is fn2, "__init__.py phai export dung function"
    print("[OK] Test 6: src.apps.monitoring.__init__.py export OK")


def test_build_strategy(symbols: dict):
    """Test 7: _build_strategy factory trả về đúng type hoặc None."""
    _build_strategy = symbols["_build_strategy"]

    # Strategy hợp lệ
    s = _build_strategy("sma_trend_early_exit", {})
    assert s is not None, "sma_trend_early_exit phai tra ve strategy"
    from src.strategies.sma_trend_early_exit import SmaTrendEarlyExitStrategy
    assert isinstance(s, SmaTrendEarlyExitStrategy)

    # Strategy không hỗ trợ → trả về None, không raise
    s_none = _build_strategy("unknown_strategy_xyz", {})
    assert s_none is None, "Strategy khong ho tro phai tra ve None"

    print("[OK] Test 7: _build_strategy factory OK")


def test_no_cross_app_imports():
    """Test 8: Không có cross-app import (apps.X import apps.Y)."""
    import ast
    with open("src/apps/monitoring/exit_monitor_service.py", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
            # Không được import từ apps.X khác (chỉ apps.monitoring là OK)
            if module.startswith("src.apps.") and not module.startswith("src.apps.monitoring"):
                raise AssertionError(
                    f"Cross-app import bi cam: {module} (dong {node.lineno})"
                )
    print("[OK] Test 8: Khong co cross-app import")


def test_main_py_integration():
    """Test 9: main.py đã có setup_exit_monitor_job call."""
    with open("main.py", encoding="utf-8") as f:
        content = f.read()
    assert "setup_exit_monitor_job" in content, \
        "main.py phai goi setup_exit_monitor_job"
    assert "from src.apps.monitoring import setup_exit_monitor_job" in content, \
        "main.py phai import tu src.apps.monitoring"
    print("[OK] Test 9: main.py da tich hop setup_exit_monitor_job")


if __name__ == "__main__":
    print("=" * 55)
    print("  ExitMonitorService — Verification Tests")
    print("=" * 55)

    try:
        symbols = test_imports()
        test_async_methods(symbols)
        test_constants(symbols)
        test_exchange_cache(symbols)
        test_setup_function(symbols)
        test_package_init()
        test_build_strategy(symbols)
        test_no_cross_app_imports()
        test_main_py_integration()

        print()
        print("=" * 55)
        print("  TAT CA 9 KIEM TRA PASS")
        print("=" * 55)
        sys.exit(0)

    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected error: {e}")
        traceback.print_exc()
        sys.exit(1)
