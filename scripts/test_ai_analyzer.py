"""
test_ai_analyzer.py — Test nhanh AI Strategy Analyzer.

Unit tests (khong can GEMINI_API_KEY):
    venv\\Scripts\\python.exe scripts/test_ai_analyzer.py

Live test (can GEMINI_API_KEY trong .env):
    venv\\Scripts\\python.exe scripts/test_ai_analyzer.py --live
"""
import asyncio
import sys
import inspect

sys.path.insert(0, ".")


# ── Mock OHLCV data ───────────────────────────────────────────────────────────

def _make_mock_ohlcv(n: int = 15) -> list:
    """Tạo dữ liệu OHLCV giả cho test."""
    import time
    base_price = 95_000.0
    base_ts    = int(time.time() * 1000) - n * 300_000  # 5m candles
    candles = []
    for i in range(n):
        ts    = base_ts + i * 300_000
        open_ = base_price + i * 50
        high  = open_ + 200
        low   = open_ - 100
        close = open_ + 150
        vol   = 10.5 + i * 0.3
        candles.append([ts, open_, high, low, close, vol])
    return candles


_MOCK_OHLCV = _make_mock_ohlcv(15)

_MOCK_METADATA = {
    "trend":      1,
    "prev_trend": 1,
    "momentum":   "blue",
    "slope_pct":  0.0523,
    "is_sideway": False,
    "ma_color":   "blue",
    "sig_color":  "blue",
    "macd_color": "green",
}

_MOCK_INDICATORS = {
    "ma_fast":        95_200.0,
    "ma_slow":        94_800.0,
    "macd":           0.000123,
    "macd_signal":    0.000098,
    "macd_histogram": 0.000025,
}


# ── Test 1: Import ────────────────────────────────────────────────────────────

def test_imports():
    """Test 1: Import tat ca symbols tu module."""
    from src.core.ai_analyzer import (
        AIAnalysisResult,
        analyze_signal,
        _build_user_prompt,
        _parse_gemini_response,
        _format_ohlcv_table,
        _SYSTEM_PROMPT,
        _GEMINI_MODEL,
        _MAX_CONCURRENT_AI_CALLS,
        _DEFAULT_TIMEOUT_SECONDS,
        _DEFAULT_MIN_CONFIDENCE,
        _global_ai_semaphore,
    )
    print("[OK] Test 1: Import tat ca symbols OK")
    return locals()


# ── Test 2: AIAnalysisResult dataclass ───────────────────────────────────────

def test_ai_analysis_result(s: dict):
    """Test 2: AIAnalysisResult dataclass va to_metadata_dict."""
    AIAnalysisResult = s["AIAnalysisResult"]

    r = AIAnalysisResult(
        decision="approve",
        confidence_score=85,
        analysis="Strong bullish momentum confirmed by MACD.",
        raw_response='{"decision":"approve","confidence_score":85,"analysis":"..."}',
        latency_ms=342.5,
    )
    meta = r.to_metadata_dict()
    assert meta["ai_decision"]         == "approve"
    assert meta["ai_confidence_score"] == 85
    assert meta["ai_analysis"]         == "Strong bullish momentum confirmed by MACD."
    assert meta["ai_latency_ms"]       == 342.5
    assert meta["ai_skipped_reason"]   == ""

    # Skip result
    skip = AIAnalysisResult(
        decision="skip",
        confidence_score=0,
        analysis="",
        skipped_reason="GEMINI_API_KEY chua duoc cau hinh",
    )
    skip_meta = skip.to_metadata_dict()
    assert skip_meta["ai_decision"] == "skip"
    assert skip_meta["ai_skipped_reason"] != ""

    print("[OK] Test 2: AIAnalysisResult dataclass va to_metadata_dict OK")


# ── Test 3: _format_ohlcv_table ──────────────────────────────────────────────

def test_format_ohlcv_table(s: dict):
    """Test 3: _format_ohlcv_table format dung so dong."""
    fn = s["_format_ohlcv_table"]
    table = fn(_MOCK_OHLCV)
    lines = [l for l in table.split("\n") if l.strip()]
    # Header + separator + 10 data rows (chi lay 10 nen cuoi)
    assert len(lines) == 12, f"Phai co 12 dong (header+sep+10 nen), got {len(lines)}"
    assert "Open" in lines[0], "Header phai co 'Open'"
    print(f"[OK] Test 3: _format_ohlcv_table — {len(lines)} dong (header+sep+10 nen)")


# ── Test 4: _build_user_prompt ────────────────────────────────────────────────

def test_build_user_prompt(s: dict):
    """Test 4: _build_user_prompt chua du thong tin can thiet."""
    fn = s["_build_user_prompt"]
    prompt = fn(
        signal_type="long",
        symbol="BTC/USDT",
        strategy_name="sma_macd_cross",
        signal_reason="MACD golden cross + MA bullish",
        ohlcv=_MOCK_OHLCV,
        current_price=95_500.0,
        timeframe="5m",
        metadata=_MOCK_METADATA,
        indicator_data=_MOCK_INDICATORS,
    )
    assert "LONG" in prompt,           "Phai co direction LONG"
    assert "BTC/USDT" in prompt,       "Phai co symbol"
    assert "sma_macd_cross" in prompt, "Phai co strategy name"
    assert "MACD golden cross" in prompt, "Phai co signal reason"
    assert "Momentum" in prompt,       "Phai co momentum indicator"
    assert "Slope" in prompt,          "Phai co slope"
    assert "JSON" in prompt,           "Phai nhac AI tra ve JSON"
    print(f"[OK] Test 4: _build_user_prompt — {len(prompt)} chars, du thong tin")


# ── Test 5: _parse_gemini_response ───────────────────────────────────────────

def test_parse_gemini_response(s: dict):
    """Test 5: _parse_gemini_response xu ly cac format khac nhau."""
    fn = s["_parse_gemini_response"]

    # Case 1: JSON thuan
    d, c, a = fn('{"decision":"approve","confidence_score":85,"analysis":"Strong trend."}')
    assert d == "approve" and c == 85 and "Strong" in a

    # Case 2: JSON trong markdown code block
    d, c, a = fn('```json\n{"decision":"reject","confidence_score":35,"analysis":"Weak."}\n```')
    assert d == "reject" and c == 35

    # Case 3: JSON voi text thua truoc/sau
    d, c, a = fn('Here is my analysis:\n{"decision":"approve","confidence_score":72,"analysis":"OK."}\nDone.')
    assert d == "approve" and c == 72

    # Case 4: confidence_score bi clamp
    d, c, a = fn('{"decision":"approve","confidence_score":150,"analysis":"X"}')
    assert c == 100, f"confidence phai bi clamp ve 100, got {c}"

    d, c, a = fn('{"decision":"reject","confidence_score":-10,"analysis":"X"}')
    assert c == 0, f"confidence phai bi clamp ve 0, got {c}"

    # Case 5: decision khong hop le → raise ValueError
    try:
        fn('{"decision":"maybe","confidence_score":50,"analysis":"X"}')
        assert False, "Phai raise ValueError"
    except ValueError:
        pass

    print("[OK] Test 5: _parse_gemini_response — 5 cases pass (clamp, markdown, text-extra)")


# ── Test 6: System Prompt quality ────────────────────────────────────────────

def test_system_prompt(s: dict):
    """Test 6: System Prompt co du cac yeu to quan trong."""
    prompt = s["_SYSTEM_PROMPT"]
    required_keywords = [
        "Price Action",
        "approve",
        "reject",
        "confidence_score",
        "JSON",
        "analysis",
        "candle",
    ]
    for kw in required_keywords:
        assert kw.lower() in prompt.lower(), f"System prompt thieu keyword: {kw!r}"
    assert len(prompt) > 500, f"System prompt qua ngan: {len(prompt)} chars"
    print(f"[OK] Test 6: System Prompt — {len(prompt)} chars, du {len(required_keywords)} keywords")


# ── Test 7: analyze_signal khi khong co API key ───────────────────────────────

async def test_analyze_signal_no_api_key(s: dict):
    """Test 7: analyze_signal tra ve skip khi khong co GEMINI_API_KEY."""
    import os
    analyze_signal = s["analyze_signal"]

    # Xoa API key neu co
    original = os.environ.pop("GEMINI_API_KEY", None)
    try:
        result = await analyze_signal(
            signal_type="long",
            symbol="BTC/USDT",
            strategy_name="sma_macd_cross",
            signal_reason="Test signal",
            ohlcv=_MOCK_OHLCV,
            current_price=95_500.0,
            timeframe="5m",
            metadata=_MOCK_METADATA,
            indicator_data=_MOCK_INDICATORS,
        )
        assert result.decision == "skip", f"Phai la skip, got {result.decision!r}"
        assert result.confidence_score == 0
        assert "GEMINI_API_KEY" in result.skipped_reason
        print(f"[OK] Test 7: analyze_signal skip khi khong co API key: {result.skipped_reason!r}")
    finally:
        if original:
            os.environ["GEMINI_API_KEY"] = original


# ── Test 8: Semaphore ton tai va dung gia tri ─────────────────────────────────

def test_semaphore(s: dict):
    """Test 8: Global semaphore ton tai va dung gia tri."""
    sem = s["_global_ai_semaphore"]
    max_calls = s["_MAX_CONCURRENT_AI_CALLS"]
    assert isinstance(sem, asyncio.Semaphore), "Phai la asyncio.Semaphore"
    assert max_calls == 3, f"Expected 3, got {max_calls}"
    print(f"[OK] Test 8: Global semaphore — max_concurrent={max_calls}")


# ── Test 9: bot_engine co _run_ai_filter ─────────────────────────────────────

def test_bot_engine_ai_filter():
    """Test 9: BotEngine co _run_ai_filter method."""
    import ast
    with open("src/core/bot_engine.py", encoding="utf-8") as f:
        source = f.read()
        tree = ast.parse(source)

    bot_engine_class = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "BotEngine"
    )
    method_names = [
        n.name for n in ast.walk(bot_engine_class)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]
    assert "_run_ai_filter" in method_names, \
        f"BotEngine phai co _run_ai_filter, co: {method_names}"
    assert "_run_ai_filter" in source, "bot_engine phai goi _run_ai_filter"
    assert "ai_filter_enabled" in source, "phai check ai_filter_enabled"
    assert "AI REJECT" in source, "phai log AI REJECT"
    print("[OK] Test 9: BotEngine._run_ai_filter ton tai va duoc tich hop")


# ── Test 10: Live test (optional) ────────────────────────────────────────────

async def test_live_analyze_signal():
    """Test 10 (Live): Goi Gemini API that voi mock signal."""
    from dotenv import load_dotenv
    load_dotenv()

    import os
    if not os.getenv("GEMINI_API_KEY"):
        print("[SKIP] Test 10 (Live): GEMINI_API_KEY chua duoc cau hinh")
        return

    from src.core.ai_analyzer import analyze_signal

    print("[Live] Dang goi Gemini API...")
    result = await analyze_signal(
        signal_type="long",
        symbol="BTC/USDT",
        strategy_name="sma_macd_cross",
        signal_reason="MACD golden cross: Signal line chuyen xanh, MACD > Signal, gia tren MA",
        ohlcv=_MOCK_OHLCV,
        current_price=95_500.0,
        timeframe="5m",
        metadata=_MOCK_METADATA,
        indicator_data=_MOCK_INDICATORS,
        timeout_seconds=15.0,
        min_confidence=50,
    )

    print(f"[Live] Decision:    {result.decision.upper()}")
    print(f"[Live] Confidence:  {result.confidence_score}/100")
    print(f"[Live] Analysis:    {result.analysis}")
    print(f"[Live] Latency:     {result.latency_ms:.0f}ms")
    print(f"[Live] Metadata:    {result.to_metadata_dict()}")

    assert result.decision in ("approve", "reject", "skip"), \
        f"decision phai la approve/reject/skip, got {result.decision!r}"
    assert 0 <= result.confidence_score <= 100
    print("[OK] Test 10 (Live): Gemini API call thanh cong")


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_all():
    print("=" * 60)
    print("  AI Strategy Analyzer — Tests")
    print("=" * 60)
    print()

    s = test_imports()
    test_ai_analysis_result(s)
    test_format_ohlcv_table(s)
    test_build_user_prompt(s)
    test_parse_gemini_response(s)
    test_system_prompt(s)
    await test_analyze_signal_no_api_key(s)
    test_semaphore(s)
    test_bot_engine_ai_filter()

    if "--live" in sys.argv:
        print()
        print("--- Live Test ---")
        await test_live_analyze_signal()

    print()
    print("=" * 60)
    print("  TAT CA 9 UNIT TESTS PASS")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(run_all())
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)
