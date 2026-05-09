"""Quick test: factory finds all 14 strategies after STRATEGY_NAME added."""
import sys
sys.path.insert(0, ".")
from src.strategies.factory import StrategyFactory

names = StrategyFactory.list_names()
print(f"Found {len(names)} strategies:")
for n in names:
    cls = StrategyFactory.get_strategy_class(n)
    lb = cls.get_required_lookback({})
    print(f"  {n:35s} lookback={lb}")

EXPECTED = [
    "adts", "custom_macd", "custom_sma", "ma_macd",
    "sma_anti_sideway", "sma_macd_cross", "sma_macd_cross_v2",
    "sma_macd_cross_v3", "sma_macd_cross_v4", "sma_macd_cross_v5",
    "sma_macd_cross_v6", "sma_macd_cross_v7", "sma_pullback",
    "sma_trend_early_exit",
]
missing = [n for n in EXPECTED if n not in names]
extra   = [n for n in names if n not in EXPECTED]

if missing:
    print(f"\n[FAIL] Missing: {missing}")
    sys.exit(1)
if extra:
    print(f"\n[INFO] Extra (new strategies): {extra}")

print(f"\n[OK] All {len(EXPECTED)} expected strategies found!")

# Test create
s = StrategyFactory.create("ma_macd", {})
print(f"[OK] create('ma_macd') -> {type(s).__name__}")

s2 = StrategyFactory.create("adts", {})
print(f"[OK] create('adts') -> {type(s2).__name__}")

# Test requires_one_shot_check
one_shot = [n for n in names if StrategyFactory.get_strategy_class(n).requires_one_shot_check]
print(f"[OK] requires_one_shot_check=True: {one_shot}")
