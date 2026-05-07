"""
test_concurrency.py — Kiem tra tinh song song cua run_once va
concurrency-safety cua _ExchangeCache.

Chay: venv\\Scripts\\python.exe scripts/test_concurrency.py
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")

from src.apps.monitoring.exit_monitor_service import _ExchangeCache


# ── Test 1: _ExchangeCache khong tao connection trung lap ────────────────────

async def test_no_duplicate_connections():
    """10 coroutine cung goi get_or_create(account_id=1) dong thoi.
    Ket qua: chi dung 1 lan connect(), tat ca nhan cung 1 instance.
    """
    connect_count = 0

    class MockAccount:
        id   = 1
        name = "TestAccount"
        mode = "testnet"
        api_key    = "fake"
        api_secret = "fake"

    class MockExchange:
        async def connect(self):
            nonlocal connect_count
            # Gia lap do tre mang de tang kha nang race condition
            await asyncio.sleep(0.05)
            connect_count += 1

        async def close(self):
            pass

    # Monkey-patch create_exchange_from_account
    import src.apps.monitoring.exit_monitor_service as svc
    original = svc.create_exchange_from_account

    def mock_factory(account):
        return MockExchange()

    svc.create_exchange_from_account = mock_factory

    try:
        cache = _ExchangeCache()
        account = MockAccount()

        # Chay 10 coroutine dong thoi, tat ca cung account_id=1
        results = await asyncio.gather(*[
            cache.get_or_create(account, "futures")
            for _ in range(10)
        ])

        # Tat ca phai nhan cung 1 instance
        assert all(r is results[0] for r in results), \
            "Tat ca coroutine phai nhan cung 1 exchange instance"

        # Chi dung 1 lan connect()
        assert connect_count == 1, \
            f"connect() phai duoc goi dung 1 lan, thuc te: {connect_count}"

        print(f"[OK] Test 1: No duplicate connections "
              f"(10 concurrent requests -> {connect_count} connect call)")
    finally:
        svc.create_exchange_from_account = original
        await cache.close_all()


# ── Test 2: Cac account khac nhau tao connection doc lap ─────────────────────

async def test_separate_connections_per_account():
    """3 account khac nhau → 3 connection rieng biet."""
    connect_calls = []

    class MockAccount:
        def __init__(self, account_id):
            self.id         = account_id
            self.name       = f"Account{account_id}"
            self.mode       = "testnet"
            self.api_key    = "fake"
            self.api_secret = "fake"

    class MockExchange:
        def __init__(self, account_id):
            self._account_id = account_id

        async def connect(self):
            connect_calls.append(self._account_id)

        async def close(self):
            pass

    import src.apps.monitoring.exit_monitor_service as svc
    original = svc.create_exchange_from_account

    def mock_factory(account):
        return MockExchange(account.id)

    svc.create_exchange_from_account = mock_factory

    try:
        cache = _ExchangeCache()
        accounts = [MockAccount(i) for i in range(1, 4)]

        # Moi account goi 5 lan dong thoi
        tasks = [
            cache.get_or_create(acc, "futures")
            for acc in accounts
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)

        # Moi account chi connect 1 lan
        assert len(connect_calls) == 3, \
            f"Phai co 3 connect calls (1 per account), thuc te: {connect_calls}"
        assert sorted(connect_calls) == [1, 2, 3], \
            f"Moi account phai connect dung 1 lan: {connect_calls}"

        # 5 ket qua cua cung account phai la cung instance
        for acc in accounts:
            acc_results = [r for r, a in zip(results, [a for a in accounts for _ in range(5)])
                           if a.id == acc.id]
            assert all(r is acc_results[0] for r in acc_results), \
                f"Account {acc.id}: tat ca phai nhan cung instance"

        print(f"[OK] Test 2: Separate connections per account "
              f"(3 accounts × 5 requests → {len(connect_calls)} connect calls)")
    finally:
        svc.create_exchange_from_account = original
        await cache.close_all()


# ── Test 3: gather nhanh hon sequential ──────────────────────────────────────

async def test_gather_faster_than_sequential():
    """asyncio.gather chay nhanh hon vong lap for-await khi co I/O."""
    DELAY = 0.05   # 50ms moi task (gia lap fetch OHLCV)
    N     = 10     # 10 trade

    async def slow_task(_):
        await asyncio.sleep(DELAY)

    # Sequential
    t0 = time.perf_counter()
    for i in range(N):
        await slow_task(i)
    sequential_time = time.perf_counter() - t0

    # Parallel
    t0 = time.perf_counter()
    await asyncio.gather(*[slow_task(i) for i in range(N)])
    parallel_time = time.perf_counter() - t0

    speedup = sequential_time / parallel_time
    assert parallel_time < sequential_time * 0.5, \
        f"gather phai nhanh hon it nhat 2x: sequential={sequential_time:.3f}s, " \
        f"parallel={parallel_time:.3f}s"

    print(f"[OK] Test 3: gather speedup {speedup:.1f}x "
          f"(sequential={sequential_time:.3f}s -> parallel={parallel_time:.3f}s "
          f"for {N} tasks x {DELAY*1000:.0f}ms)")


# ── Test 4: return_exceptions=True khong de 1 loi huy tat ca ────────────────

async def test_return_exceptions_isolation():
    """1 task loi khong lam huy cac task khac khi dung return_exceptions=True."""
    results_log = []

    async def task_ok(i):
        await asyncio.sleep(0.01)
        results_log.append(f"ok_{i}")
        return f"ok_{i}"

    async def task_fail():
        await asyncio.sleep(0.01)
        raise ValueError("Loi gia lap")

    tasks = [task_ok(0), task_fail(), task_ok(1), task_fail(), task_ok(2)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ok_count  = sum(1 for r in results if isinstance(r, str))
    err_count = sum(1 for r in results if isinstance(r, Exception))

    assert ok_count  == 3, f"Phai co 3 task thanh cong, thuc te: {ok_count}"
    assert err_count == 2, f"Phai co 2 exception, thuc te: {err_count}"
    assert len(results_log) == 3, "3 task ok phai chay xong"

    print(f"[OK] Test 4: return_exceptions isolation "
          f"({ok_count} OK + {err_count} errors, khong task nao bi huy)")


# ── Test 5: close_all don dep locks ──────────────────────────────────────────

async def test_close_all_cleanup():
    """close_all() phai xoa ca _cache lan _locks."""
    cache = _ExchangeCache()

    class FakeExchange:
        async def connect(self): pass
        async def close(self): pass

    class FakeAccount:
        id = 99; name = "x"; mode = "testnet"
        api_key = "k"; api_secret = "s"

    import src.apps.monitoring.exit_monitor_service as svc
    original = svc.create_exchange_from_account
    svc.create_exchange_from_account = lambda _: FakeExchange()

    try:
        await cache.get_or_create(FakeAccount(), "futures")
        assert len(cache._cache) == 1
        assert len(cache._locks) == 1

        await cache.close_all()

        assert len(cache._cache) == 0, "_cache phai rong sau close_all"
        assert len(cache._locks) == 0, "_locks phai rong sau close_all"
        print("[OK] Test 5: close_all() don dep ca _cache va _locks")
    finally:
        svc.create_exchange_from_account = original


# ── Runner ────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  Concurrency & _ExchangeCache — Tests")
    print("=" * 60)
    print()

    await test_no_duplicate_connections()
    await test_separate_connections_per_account()
    await test_gather_faster_than_sequential()
    await test_return_exceptions_isolation()
    await test_close_all_cleanup()

    print()
    print("=" * 60)
    print("  TAT CA 5 KIEM TRA PASS")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)
