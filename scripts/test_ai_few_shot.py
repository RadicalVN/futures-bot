"""
test_ai_few_shot.py — Test few-shot logic trong ai_analyzer.py.

Chay: venv\\Scripts\\python.exe scripts/test_ai_few_shot.py
"""
import asyncio
import sys
sys.path.insert(0, ".")

from src.core.ai_analyzer import (
    _build_few_shot_section,
    _fetch_dislike_examples,
    _FEW_SHOT_LIMIT,
    _FEW_SHOT_SNIPPET_MAX_CHARS,
    _SYSTEM_PROMPT,
)

tests_passed = 0

def check(name, condition, detail=""):
    global tests_passed
    if condition:
        print(f"[OK] {name}")
        tests_passed += 1
    else:
        print(f"[FAIL] {name}: {detail}")
        sys.exit(1)


# ── Test 1: _build_few_shot_section voi examples rong ────────────────────────

def test_empty_examples():
    result = _build_few_shot_section([])
    check("empty examples -> empty string", result == "", f"got {result!r}")


# ── Test 2: _build_few_shot_section voi 1 example ────────────────────────────

def test_single_example():
    examples = [{
        "symbol":        "BTCUSDT",
        "signal_type":   "LONG",
        "strategy":      "sma_macd_cross",
        "ai_decision":   "approve",
        "ai_confidence": 72,
        "ai_analysis":   "Strong momentum",
        "realized_pnl":  -8.5,
        "user_comment":  "AI bo qua divergence MACD",
    }]
    result = _build_few_shot_section(examples)

    check("contains MISTAKES TO AVOID header",
          "MISTAKES TO AVOID" in result)
    check("contains historical_context tag",
          "<historical_context>" in result and "</historical_context>" in result)
    check("contains past_mistake tag",
          "<past_mistake>" in result and "</past_mistake>" in result)
    check("contains symbol",
          "BTCUSDT" in result)
    check("contains LOSS label",
          "LOSS" in result and "-8.50" in result)
    check("contains user comment",
          "divergence MACD" in result)
    check("contains lesson instruction",
          "Do NOT repeat" in result)


# ── Test 3: _build_few_shot_section voi WIN trade ────────────────────────────

def test_win_trade():
    examples = [{
        "symbol":        "ETHUSDT",
        "signal_type":   "SHORT",
        "strategy":      "adts",
        "ai_decision":   "approve",
        "ai_confidence": 55,
        "ai_analysis":   "Weak signal",
        "realized_pnl":  15.3,
        "user_comment":  "",
    }]
    result = _build_few_shot_section(examples)
    check("WIN trade shows WIN label",
          "WIN" in result and "+15.30" in result)
    check("empty comment not shown",
          "User Feedback" not in result)


# ── Test 4: _build_few_shot_section voi None pnl ─────────────────────────────

def test_none_pnl():
    examples = [{
        "symbol":        "SOLUSDT",
        "signal_type":   "LONG",
        "strategy":      "sma_macd_cross",
        "ai_decision":   "approve",
        "ai_confidence": 60,
        "ai_analysis":   "",
        "realized_pnl":  None,
        "user_comment":  "Test",
    }]
    result = _build_few_shot_section(examples)
    check("None pnl shows unknown amount",
          "unknown amount" in result)


# ── Test 5: _build_few_shot_section gioi han so luong ────────────────────────

def test_limit():
    examples = [
        {
            "symbol": f"TOKEN{i}USDT", "signal_type": "LONG",
            "strategy": "sma_macd_cross", "ai_decision": "approve",
            "ai_confidence": 70, "ai_analysis": "", "realized_pnl": -5.0,
            "user_comment": "",
        }
        for i in range(5)
    ]
    result = _build_few_shot_section(examples)
    # Tat ca 5 examples duoc render (limit duoc xu ly o _fetch_dislike_examples)
    check("all 5 examples rendered",
          result.count("<past_mistake>") == 5)


# ── Test 6: Dynamic system prompt co few-shot section ────────────────────────

def test_dynamic_prompt_structure():
    examples = [{
        "symbol": "BTCUSDT", "signal_type": "LONG",
        "strategy": "sma_macd_cross", "ai_decision": "approve",
        "ai_confidence": 65, "ai_analysis": "test",
        "realized_pnl": -10.0, "user_comment": "Wrong call",
    }]
    few_shot = _build_few_shot_section(examples)
    dynamic_prompt = _SYSTEM_PROMPT + few_shot

    check("base system prompt preserved",
          "Professional Price Action Trader" in dynamic_prompt)
    check("few-shot appended after base prompt",
          dynamic_prompt.index("MISTAKES TO AVOID") > dynamic_prompt.index("Professional"))
    check("JSON format instruction still present",
          '"decision"' in dynamic_prompt)


# ── Test 7: _fetch_dislike_examples fail-open khi khong co DB ────────────────

async def test_fetch_fail_open():
    # Khong co DB connection -> phai tra ve [] khong crash
    result = await _fetch_dislike_examples("sma_macd_cross")
    check("fetch fail-open returns list",
          isinstance(result, list))
    # Ket qua co the la [] (khong co DB) hoac list examples
    check("fetch returns list (empty or with data)",
          isinstance(result, list))


# ── Test 8: FEW_SHOT_LIMIT constant ──────────────────────────────────────────

def test_constants():
    check("_FEW_SHOT_LIMIT is 3", _FEW_SHOT_LIMIT == 3)
    check("_SYSTEM_PROMPT is non-empty", len(_SYSTEM_PROMPT) > 100)


# ── Runner ────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 55)
    print("  AI Few-shot Learning — Tests")
    print("=" * 55)
    print()

    test_empty_examples()
    test_single_example()
    test_win_trade()
    test_none_pnl()
    test_limit()
    test_dynamic_prompt_structure()
    await test_fetch_fail_open()
    test_constants()

    print()
    print(f"=== TAT CA {tests_passed} TESTS PASS ===")


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
