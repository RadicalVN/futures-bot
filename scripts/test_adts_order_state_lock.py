"""
test_adts_order_state_lock.py — Kiểm thử Per-symbol Lock cho _order_states.

Mô phỏng 3 kịch bản:
  1. Lock isolation: 2 symbol chạy song song không block lẫn nhau
  2. Lock serialization: cùng 1 symbol serialize đúng thứ tự
  3. Lock cleanup: clear_order_state() xóa lock khỏi dict

Chạy: venv\Scripts\python.exe scripts/test_adts_order_state_lock.py
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")

from src.strategies.adts_strategy import ADTSStrategy


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_strategy() -> ADTSStrategy:
    return ADTSStrategy({})


# ── Test 1: Lock isolation — 2 symbol không block nhau ───────────────────────

async def test_lock_isolation_different_symbols() -> None:
    print("\n" + "="*60)
    print("TEST 1: Lock isolation — 2 symbol chạy song song không block nhau")
    print("="*60)

    strategy = _make_strategy()
    results: list[str] = []

    async def slow_register(sym: str, delay: float) -> None:
        """Mô phỏng register với delay bên trong lock."""
        lock = strategy._get_order_state_lock(sym)
        async with lock:
            await asyncio.sleep(delay)
            strategy._order_states[sym] = None  # type: ignore
            results.append(sym)

    start = time.monotonic()
    # Chạy song song 2 symbol khác nhau, mỗi cái delay 0.05s
    await asyncio.gather(
        slow_register("BTC/USDT", 0.05),
        slow_register("ETH/USDT", 0.05),
    )
    elapsed = time.monotonic() - start

    # Nếu lock isolation đúng: tổng thời gian ≈ 0.05s (song song)
    # Nếu dùng global lock: tổng thời gian ≈ 0.10s (tuần tự)
    assert elapsed < 0.09, (
        f"2 symbol khác nhau phải chạy song song (elapsed={elapsed:.3f}s < 0.09s)"
    )
    assert set(results) == {"BTC/USDT", "ETH/USDT"}
    print(f"  ✅ Elapsed = {elapsed:.3f}s (< 0.09s) — song song, không block nhau")
    print(f"  ✅ Cả 2 symbol đều hoàn thành: {results}")
    print("  → PASS")


# ── Test 2: Lock serialization — cùng symbol serialize đúng thứ tự ───────────

async def test_lock_serialization_same_symbol() -> None:
    print("\n" + "="*60)
    print("TEST 2: Lock serialization — cùng symbol serialize đúng thứ tự")
    print("="*60)

    strategy = _make_strategy()
    order: list[int] = []

    async def task(n: int, delay: float) -> None:
        async with strategy._get_order_state_lock("BTC/USDT"):
            await asyncio.sleep(delay)
            order.append(n)

    start = time.monotonic()
    # Chạy song song nhưng cùng symbol → phải serialize
    await asyncio.gather(task(1, 0.05), task(2, 0.01), task(3, 0.01))
    elapsed = time.monotonic() - start

    # Tổng thời gian ≈ 0.07s (tuần tự: 0.05 + 0.01 + 0.01)
    assert elapsed >= 0.06, (
        f"Cùng symbol phải serialize (elapsed={elapsed:.3f}s >= 0.06s)"
    )
    # Task 1 acquire trước → hoàn thành trước
    assert order[0] == 1, f"Task 1 phải hoàn thành đầu tiên, got order={order}"
    print(f"  ✅ Elapsed = {elapsed:.3f}s (>= 0.06s) — serialize đúng")
    print(f"  ✅ Thứ tự hoàn thành: {order} (task 1 trước)")
    print("  → PASS")


# ── Test 3: Lock cleanup — clear_order_state xóa lock ────────────────────────

async def test_lock_cleanup_on_clear() -> None:
    print("\n" + "="*60)
    print("TEST 3: Lock cleanup — clear_order_state() xóa lock khỏi dict")
    print("="*60)

    strategy = _make_strategy()

    # Tạo lock cho symbol
    lock = strategy._get_order_state_lock("BTC/USDT")
    assert "BTC/USDT" in strategy._order_states_locks
    print(f"  ✅ Lock tạo: 'BTC/USDT' in _order_states_locks = True")

    # clear_order_state phải xóa lock
    await strategy.clear_order_state("BTC/USDT")
    assert "BTC/USDT" not in strategy._order_states_locks, (
        "Lock phải được xóa sau clear_order_state()"
    )
    print(f"  ✅ Sau clear: 'BTC/USDT' in _order_states_locks = False")

    # Lock mới được tạo lại khi cần
    new_lock = strategy._get_order_state_lock("BTC/USDT")
    assert new_lock is not lock, "Lock mới phải là object khác"
    print(f"  ✅ Lock mới được tạo lại (object khác): {id(new_lock) != id(lock)}")
    print("  → PASS")


# ── Test 4: register_order_state là async ────────────────────────────────────

async def test_register_is_async() -> None:
    print("\n" + "="*60)
    print("TEST 4: register_order_state() là async method")
    print("="*60)

    strategy = _make_strategy()
    import inspect
    assert inspect.iscoroutinefunction(strategy.register_order_state), (
        "register_order_state phải là async def"
    )
    print("  ✅ register_order_state là coroutine function")

    # Gọi thực tế (không có event loop running task nên create_task sẽ fail — bỏ qua)
    try:
        await strategy.register_order_state(
            symbol="BTC/USDT", side="long", entry_price=95000.0,
            amount=0.01, stop_loss=93575.0, take_profit_1=96710.0,
            tp2_initial_trail=93000.0, atr=950.0, bot_id=None,
        )
    except RuntimeError:
        pass  # create_task có thể fail nếu không có running loop — OK

    assert "BTC/USDT" in strategy._order_states
    assert strategy._order_states["BTC/USDT"].entry_price == 95000.0
    print("  ✅ register_order_state() ghi đúng vào _order_states")
    print("  → PASS")


# ── Test 5: clear_order_state là async ───────────────────────────────────────

async def test_clear_is_async() -> None:
    print("\n" + "="*60)
    print("TEST 5: clear_order_state() là async method")
    print("="*60)

    strategy = _make_strategy()
    import inspect
    assert inspect.iscoroutinefunction(strategy.clear_order_state), (
        "clear_order_state phải là async def"
    )
    print("  ✅ clear_order_state là coroutine function")

    # Inject state rồi clear
    strategy._order_states["ETH/USDT"] = None  # type: ignore
    strategy._get_order_state_lock("ETH/USDT")  # tạo lock
    await strategy.clear_order_state("ETH/USDT")

    assert "ETH/USDT" not in strategy._order_states
    assert "ETH/USDT" not in strategy._order_states_locks
    print("  ✅ State và lock đều được xóa sau clear_order_state()")
    print("  → PASS")


# ── Test 6: _get_order_state_lock trả về cùng object cho cùng symbol ─────────

async def test_lock_identity() -> None:
    print("\n" + "="*60)
    print("TEST 6: _get_order_state_lock() trả về cùng object cho cùng symbol")
    print("="*60)

    strategy = _make_strategy()
    lock_a = strategy._get_order_state_lock("BTC/USDT")
    lock_b = strategy._get_order_state_lock("BTC/USDT")
    lock_c = strategy._get_order_state_lock("ETH/USDT")

    assert lock_a is lock_b, "Cùng symbol phải trả về cùng lock object"
    assert lock_a is not lock_c, "Khác symbol phải trả về lock object khác"
    print(f"  ✅ BTC/USDT lock_a is lock_b: {lock_a is lock_b}")
    print(f"  ✅ BTC/USDT lock_a is not ETH/USDT lock_c: {lock_a is not lock_c}")
    print("  → PASS")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n🧪 ADTS Per-symbol Order State Lock — Test Suite")
    print("=" * 60)

    await test_lock_isolation_different_symbols()
    await test_lock_serialization_same_symbol()
    await test_lock_cleanup_on_clear()
    await test_register_is_async()
    await test_clear_is_async()
    await test_lock_identity()

    print("\n" + "="*60)
    print("✅ Tất cả 6 tests PASSED")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
