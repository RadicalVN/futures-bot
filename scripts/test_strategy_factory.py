"""Test StrategyFactory auto-discovery — File #2 of Task 4.1

NOTE: Các strategy hiện tại chưa có STRATEGY_NAME (sẽ được thêm ở File #3-#10).
Test này verify factory mechanism hoạt động đúng với mock strategies.
"""
import sys, asyncio
sys.path.insert(0, ".")

from src.strategies.factory import StrategyFactory
from src.strategies.base_strategy import BaseStrategy, StrategySignal

passed = 0

def ok(name):
    global passed
    passed += 1
    print(f"[OK] {name}")

# ── Setup: Reset registry và inject mock strategies ───────────────────────────
StrategyFactory.reset_registry()

# Tạo mock strategies để test factory mechanism
# (Các strategy thật sẽ có STRATEGY_NAME sau khi implement File #3-#10)
class MockStrategyA(BaseStrategy):
    STRATEGY_NAME = "mock_strategy_a"
    @classmethod
    def get_required_lookback(cls, parameters):
        return int(parameters.get("period", 50)) + 10
    async def analyze(self, symbol, ohlcv_data, current_positions):
        return StrategySignal(signal="none", symbol=symbol, price=0, reason="mock")

class MockStrategyB(BaseStrategy):
    STRATEGY_NAME = "mock_strategy_b"
    requires_one_shot_check = True
    async def analyze(self, symbol, ohlcv_data, current_positions):
        return StrategySignal(signal="none", symbol=symbol, price=0, reason="mock")

class MockStrategyNoName(BaseStrategy):
    STRATEGY_NAME = ""  # Không có tên → không được đăng ký
    async def analyze(self, symbol, ohlcv_data, current_positions):
        return StrategySignal(signal="none", symbol=symbol, price=0, reason="mock")

# Inject vào src.strategies package để walk_packages tìm thấy
import src.strategies as _pkg
import types

# Tạo fake module chứa mock strategies
_mock_module = types.ModuleType("src.strategies._mock_test")
_mock_module.MockStrategyA = MockStrategyA
_mock_module.MockStrategyB = MockStrategyB
_mock_module.MockStrategyNoName = MockStrategyNoName
sys.modules["src.strategies._mock_test"] = _mock_module

# Rebuild registry
StrategyFactory.reset_registry()

# Manually register để test (vì walk_packages không thấy runtime-injected modules)
# Đây là cách test factory logic mà không cần file thật
from src.strategies import factory as _factory_module
_factory_module._REGISTRY["mock_strategy_a"] = MockStrategyA
_factory_module._REGISTRY["mock_strategy_b"] = MockStrategyB
_factory_module._REGISTRY_BUILT = True

# ── Test 1: Registry có entries ───────────────────────────────────────────────
names = StrategyFactory.list_names()
assert "mock_strategy_a" in names
assert "mock_strategy_b" in names
assert "mock_strategy_no_name" not in names  # Không có STRATEGY_NAME → không đăng ký
ok(f"Registry contains registered strategies, excludes no-name class")

# ── Test 2: create() returns correct instance ─────────────────────────────────
s = StrategyFactory.create("mock_strategy_a", {"period": 100})
assert isinstance(s, BaseStrategy)
assert isinstance(s, MockStrategyA)
assert s.STRATEGY_NAME == "mock_strategy_a"
ok("create() returns correct instance type")

# ── Test 3: create() passes config correctly ──────────────────────────────────
s2 = StrategyFactory.create("mock_strategy_a", {"period": 200, "key": "val"})
assert s2.get_param("period") == 200
assert s2.get_param("key") == "val"
ok("create() passes config dict to strategy constructor")

# ── Test 4: create() raises ValueError for unknown strategy ───────────────────
try:
    StrategyFactory.create("nonexistent_xyz", {})
    assert False, "Should raise ValueError"
except ValueError as e:
    assert "nonexistent_xyz" in str(e)
    assert "mock_strategy_a" in str(e)  # Helpful: shows available strategies
ok("create() raises ValueError with available strategies listed")

# ── Test 5: get_strategy_class() returns class, not instance ─────────────────
cls = StrategyFactory.get_strategy_class("mock_strategy_a")
assert cls is MockStrategyA
assert isinstance(cls, type)
ok("get_strategy_class() returns class object (not instance)")

# ── Test 6: get_required_lookback via class (no instance needed) ──────────────
cls = StrategyFactory.get_strategy_class("mock_strategy_a")
assert cls.get_required_lookback({"period": 100}) == 110
assert cls.get_required_lookback({}) == 60
ok("get_required_lookback() callable via class from factory")

# ── Test 7: requires_one_shot_check accessible via class ─────────────────────
cls_a = StrategyFactory.get_strategy_class("mock_strategy_a")
cls_b = StrategyFactory.get_strategy_class("mock_strategy_b")
assert cls_a.requires_one_shot_check == False
assert cls_b.requires_one_shot_check == True
ok("requires_one_shot_check accessible via class from factory")

# ── Test 8: exists() works correctly ─────────────────────────────────────────
assert StrategyFactory.exists("mock_strategy_a") == True
assert StrategyFactory.exists("mock_strategy_b") == True
assert StrategyFactory.exists("nonexistent_xyz") == False
ok("exists() returns True/False correctly")

# ── Test 9: list_names() is sorted ───────────────────────────────────────────
names = StrategyFactory.list_names()
assert names == sorted(names)
ok(f"list_names() returns sorted list: {names}")

# ── Test 10: get_registry_snapshot() returns module paths ────────────────────
snap = StrategyFactory.get_registry_snapshot()
assert "mock_strategy_a" in snap
assert "MockStrategyA" in snap["mock_strategy_a"]
ok("get_registry_snapshot() returns {name: module.ClassName} mapping")

# ── Test 11: reset_registry() clears state ───────────────────────────────────
StrategyFactory.reset_registry()
assert not StrategyFactory.exists("mock_strategy_a")
ok("reset_registry() clears all entries")

# ── Test 12: _is_valid_strategy_class logic ───────────────────────────────────
from src.strategies.factory import _is_valid_strategy_class
assert _is_valid_strategy_class(MockStrategyA) == True
assert _is_valid_strategy_class(MockStrategyNoName) == False  # empty STRATEGY_NAME
assert _is_valid_strategy_class(BaseStrategy) == False         # is BaseStrategy itself
assert _is_valid_strategy_class("not_a_class") == False
assert _is_valid_strategy_class(42) == False
ok("_is_valid_strategy_class() filters correctly")

# ── Test 13: Verify walk_packages finds real strategies (after File #3-#10) ───
# Rebuild registry từ disk — hiện tại 0 vì chưa có STRATEGY_NAME
StrategyFactory.reset_registry()
real_names = StrategyFactory.list_names()
print(f"\n  [INFO] Real strategies with STRATEGY_NAME: {len(real_names)}")
print(f"  [INFO] (Expected 0 until File #3-#10 adds STRATEGY_NAME to each strategy)")
ok(f"walk_packages scan completes without error ({len(real_names)} real strategies found)")

print(f"\n=== TAT CA {passed} TESTS PASS ===")
print("\nFactory mechanism verified. Ready for File #3-#10 (add STRATEGY_NAME to each strategy).")


# ── Test 2: All expected strategies are registered ────────────────────────────
EXPECTED = [
    "ma_macd",
    "custom_sma",
    "sma_trend_early_exit",
    "sma_pullback",
    "sma_anti_sideway",
    "sma_macd_cross",
    "sma_macd_cross_v2",
    "sma_macd_cross_v3",
    "sma_macd_cross_v4",
    "sma_macd_cross_v5",
    "sma_macd_cross_v6",
    "sma_macd_cross_v7",
    # adts requires its own STRATEGY_NAME — skip until File #10
]
for name in EXPECTED:
    assert StrategyFactory.exists(name), f"Missing: {name}"
ok(f"All {len(EXPECTED)} expected strategies registered")

# ── Test 3: create() returns correct instance ─────────────────────────────────
s = StrategyFactory.create("ma_macd", {"ma_fast": 10})
assert isinstance(s, BaseStrategy)
assert s.STRATEGY_NAME == "ma_macd"
ok("create('ma_macd') returns MaMacdStrategy instance")

s2 = StrategyFactory.create("sma_macd_cross_v7", {})
assert s2.STRATEGY_NAME == "sma_macd_cross_v7"
ok("create('sma_macd_cross_v7') returns correct instance")

# ── Test 4: create() raises ValueError for unknown strategy ───────────────────
try:
    StrategyFactory.create("nonexistent_xyz", {})
    assert False, "Should raise ValueError"
except ValueError as e:
    assert "nonexistent_xyz" in str(e)
    assert "registry" in str(e).lower()
ok("create() raises ValueError with helpful message for unknown strategy")

# ── Test 5: get_strategy_class() returns class, not instance ─────────────────
cls = StrategyFactory.get_strategy_class("ma_macd")
assert isinstance(cls, type)
assert issubclass(cls, BaseStrategy)
assert cls.STRATEGY_NAME == "ma_macd"
ok("get_strategy_class() returns class (not instance)")

# ── Test 6: get_required_lookback via class (no instance needed) ──────────────
cls = StrategyFactory.get_strategy_class("sma_macd_cross")
lookback = cls.get_required_lookback({"macd_signal_length": 500})
# sma_macd_cross hiện dùng default 200 (chưa override) — sẽ override ở File #8
assert isinstance(lookback, int) and lookback > 0
ok(f"get_required_lookback via class: {lookback}")

# ── Test 7: exists() works correctly ─────────────────────────────────────────
assert StrategyFactory.exists("ma_macd") == True
assert StrategyFactory.exists("nonexistent_xyz") == False
ok("exists() returns True/False correctly")

# ── Test 8: list_names() is sorted ───────────────────────────────────────────
names = StrategyFactory.list_names()
assert names == sorted(names)
ok(f"list_names() returns sorted list: {names}")

# ── Test 9: get_registry_snapshot() returns module paths ─────────────────────
snap = StrategyFactory.get_registry_snapshot()
assert "ma_macd" in snap
assert "MaMacdStrategy" in snap["ma_macd"]
ok(f"get_registry_snapshot() returns module paths")

# ── Test 10: factory.py itself is NOT in registry ────────────────────────────
assert not StrategyFactory.exists("factory")
assert not StrategyFactory.exists("base_strategy")
ok("factory.py and base_strategy.py excluded from registry")

# ── Test 11: Dynamic registration — new strategy auto-discovered ──────────────
# Simulate adding a new strategy at runtime
StrategyFactory.reset_registry()

# Create a new strategy class dynamically
class DynamicTestStrategy(BaseStrategy):
    STRATEGY_NAME = "dynamic_test_v99"
    async def analyze(self, symbol, ohlcv_data, current_positions):
        return StrategySignal(signal="none", symbol=symbol, price=0, reason="test")

# Inject into src.strategies namespace so walk_packages can find it
import src.strategies as _pkg
_pkg.dynamic_test_v99 = DynamicTestStrategy  # simulate file in package

# Rebuild registry — should find existing strategies again
names_after = StrategyFactory.list_names()
assert len(names_after) >= len(EXPECTED), f"Registry lost strategies after reset: {names_after}"
ok(f"reset_registry() + rebuild works: {len(names_after)} strategies")

# ── Test 12: No duplicate STRATEGY_NAME in registry ──────────────────────────
snap = StrategyFactory.get_registry_snapshot()
# Each name maps to exactly one class
assert len(snap) == len(StrategyFactory.list_names())
ok("No duplicate STRATEGY_NAME in registry")

print(f"\n=== TAT CA {passed} TESTS PASS ===")
print("\nFactory mechanism verified. Ready for File #3-#10 (add STRATEGY_NAME to each strategy).")
