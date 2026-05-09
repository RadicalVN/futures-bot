"""Test base_strategy.py contract — File #1 of Task 4.1"""
import sys, inspect, asyncio
sys.path.insert(0, ".")
from src.strategies.base_strategy import BaseStrategy, StrategySignal

passed = 0

def ok(name):
    global passed
    passed += 1
    print(f"[OK] {name}")

# Test 1: StrategySignal properties
s = StrategySignal(signal="long", symbol="BTC/USDT", price=95000.0, reason="test")
assert s.is_entry and not s.is_exit and not s.is_none
ok("StrategySignal.is_entry/is_exit/is_none")

s2 = StrategySignal(signal="close_long", symbol="BTC/USDT", price=0, reason="x")
assert not s2.is_entry and s2.is_exit
ok("StrategySignal close_long is_exit")

# Test 2: Class-level attributes exist with correct defaults
assert BaseStrategy.STRATEGY_NAME == ""
assert BaseStrategy.requires_one_shot_check == False
ok("Class attributes: STRATEGY_NAME='', requires_one_shot_check=False")

# Test 3: get_required_lookback is classmethod, default=200
assert isinstance(inspect.getattr_static(BaseStrategy, "get_required_lookback"), classmethod)
assert BaseStrategy.get_required_lookback({}) == 200
ok("get_required_lookback: classmethod, default=200")

# Test 4: prepare_metadata is async
assert inspect.iscoroutinefunction(BaseStrategy.prepare_metadata)
ok("prepare_metadata: async coroutine")

# Test 5: analyze is abstract
assert getattr(BaseStrategy.analyze, "__isabstractmethod__", False)
ok("analyze: abstract method")

# Test 6: Subclass instantiation + backward compat self.name
class TestStrategy(BaseStrategy):
    STRATEGY_NAME = "test_strategy"
    async def analyze(self, symbol, ohlcv_data, current_positions):
        return StrategySignal(signal="none", symbol=symbol, price=0, reason="test")

t = TestStrategy({"key": "val"})
assert t.STRATEGY_NAME == "test_strategy"
assert t.name == "test_strategy"          # backward compat
assert t.requires_one_shot_check == False
assert t.get_param("key") == "val"
ok("Subclass: STRATEGY_NAME, self.name backward compat, get_param")

# Test 7: requires_one_shot_check override
class OneShotStrategy(BaseStrategy):
    STRATEGY_NAME = "one_shot"
    requires_one_shot_check = True
    async def analyze(self, s, o, p): pass

assert OneShotStrategy.requires_one_shot_check == True
assert OneShotStrategy({}).requires_one_shot_check == True
ok("requires_one_shot_check: override to True")

# Test 8: get_required_lookback override
class CustomLookback(BaseStrategy):
    STRATEGY_NAME = "custom_lb"
    @classmethod
    def get_required_lookback(cls, parameters):
        return int(parameters.get("period", 100)) + 50
    async def analyze(self, s, o, p): pass

assert CustomLookback.get_required_lookback({"period": 200}) == 250
assert CustomLookback.get_required_lookback({}) == 150
ok("get_required_lookback: override with parameter-based calculation")

# Test 9: prepare_metadata default returns {}
async def _test_prepare():
    result = await TestStrategy({}).prepare_metadata(None)
    assert result == {}
asyncio.run(_test_prepare())
ok("prepare_metadata: default returns {}")

# Test 10: Cannot instantiate BaseStrategy directly (abstract)
try:
    BaseStrategy({})
    assert False, "Should raise TypeError"
except TypeError:
    ok("BaseStrategy: cannot instantiate directly (abstract)")

print(f"\n=== TAT CA {passed} TESTS PASS ===")
