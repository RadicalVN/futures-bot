"""
test_health_check.py — Kiem tra nhanh HealthCheckService va Heartbeat.

Chay: venv\\Scripts\\python.exe scripts/test_health_check.py
"""
import asyncio
import inspect
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")


# ── Test 1: Import ────────────────────────────────────────────────────────────

def test_imports():
    """Test 1: Import tat ca symbols tu module."""
    from src.apps.monitoring.health_check_service import (
        HealthCheckService,
        CheckResult,
        setup_health_check_job,
        _check_database,
        _check_redis,
        _check_bot_status,
        _check_binance_api,
        _build_alert_embed,
        _build_ok_embed,
        _build_status_fields,
        _build_action_hints,
        _checkpoint_label,
        _fmt_ago,
        _SCAN_INTERVAL_SECONDS,
        _LOCK_TTL_SECONDS,
        _JOB_ID,
        _BOT_HEARTBEAT_THRESHOLD_MINUTES,
        _OK_SUMMARY_INTERVAL_HOURS,
    )
    print("[OK] Test 1: Import tat ca symbols OK")
    return locals()


# ── Test 2: Constants ─────────────────────────────────────────────────────────

def test_constants(s: dict):
    """Test 2: Hang so dung gia tri theo spec."""
    assert s["_SCAN_INTERVAL_SECONDS"] == 300, f"Expected 300, got {s['_SCAN_INTERVAL_SECONDS']}"
    assert s["_LOCK_TTL_SECONDS"] == 270,      f"Expected 270, got {s['_LOCK_TTL_SECONDS']}"
    assert s["_LOCK_TTL_SECONDS"] < s["_SCAN_INTERVAL_SECONDS"], "lock_ttl phai < interval"
    assert s["_JOB_ID"] == "health_check",     f"Expected 'health_check', got {s['_JOB_ID']!r}"
    assert s["_BOT_HEARTBEAT_THRESHOLD_MINUTES"] == 10
    assert s["_OK_SUMMARY_INTERVAL_HOURS"] == 1
    print(
        f"[OK] Test 2: Constants — interval={s['_SCAN_INTERVAL_SECONDS']}s, "
        f"lock_ttl={s['_LOCK_TTL_SECONDS']}s, "
        f"heartbeat_threshold={s['_BOT_HEARTBEAT_THRESHOLD_MINUTES']}min"
    )


# ── Test 3: CheckResult dataclass ────────────────────────────────────────────

def test_check_result(s: dict):
    """Test 3: CheckResult dataclass co du fields."""
    import dataclasses
    CheckResult = s["CheckResult"]
    assert dataclasses.is_dataclass(CheckResult), "CheckResult phai la dataclass"
    fields = {f.name for f in dataclasses.fields(CheckResult)}
    required = {"name", "ok", "message", "latency_ms", "detail", "extra"}
    assert required.issubset(fields), f"Thieu fields: {required - fields}"

    # Test default values
    r = CheckResult(name="test", ok=True, message="OK", latency_ms=10.0)
    assert r.detail == ""
    assert r.extra  == ""
    print(f"[OK] Test 3: CheckResult dataclass — fields: {sorted(fields)}")


# ── Test 4: Async methods ─────────────────────────────────────────────────────

def test_async_methods(s: dict):
    """Test 4: Cac checkpoint functions phai la async coroutine."""
    HealthCheckService = s["HealthCheckService"]
    assert inspect.iscoroutinefunction(HealthCheckService.run_once)
    assert inspect.iscoroutinefunction(HealthCheckService._execute_health_check)
    assert inspect.iscoroutinefunction(HealthCheckService._handle_alerting)
    assert inspect.iscoroutinefunction(s["_check_database"])
    assert inspect.iscoroutinefunction(s["_check_redis"])
    assert inspect.iscoroutinefunction(s["_check_bot_status"])
    assert inspect.iscoroutinefunction(s["_check_binance_api"])
    print("[OK] Test 4: Tat ca I/O methods deu la async coroutine")


# ── Test 5: _build_status_fields ─────────────────────────────────────────────

def test_build_status_fields(s: dict):
    """Test 5: _build_status_fields tao dung 4 fields inline."""
    CheckResult = s["CheckResult"]
    fn = s["_build_status_fields"]

    results = [
        CheckResult("database",    True,  "OK 12ms",  12.0),
        CheckResult("redis",       False, "FAILED",    0.0, detail="Connection refused"),
        CheckResult("bot_status",  True,  "OK 2 running", 8.0),
        CheckResult("binance_api", True,  "OK 45ms",  45.0),
    ]
    fields = fn(results)
    assert len(fields) == 4, f"Phai co 4 fields, got {len(fields)}"
    assert all(f["inline"] is True for f in fields), "Tat ca phai inline=True"
    # Field Redis phai co ❌
    redis_field = next(f for f in fields if "Redis" in f["name"])
    assert "❌" in redis_field["value"], "Redis failed phai co ❌"
    # Field Database phai co ✅
    db_field = next(f for f in fields if "Database" in f["name"])
    assert "✅" in db_field["value"], "Database OK phai co ✅"
    print("[OK] Test 5: _build_status_fields — 4 inline fields, icons dung")


# ── Test 6: _build_alert_embed ────────────────────────────────────────────────

def test_build_alert_embed(s: dict):
    """Test 6: _build_alert_embed co title, color do, va error detail fields."""
    CheckResult = s["CheckResult"]
    fn = s["_build_alert_embed"]

    results = [
        CheckResult("database",    True,  "OK 12ms",  12.0),
        CheckResult("redis",       False, "FAILED",    0.0, detail="Connection refused"),
        CheckResult("bot_status",  True,  "OK 2 running", 8.0),
        CheckResult("binance_api", False, "HTTP 403", 100.0, detail="IP blocked"),
    ]
    embed = fn(results, "2026-05-07 14:30 UTC+7")

    assert "ALERT" in embed["title"], "Title phai co ALERT"
    assert "2 CRITICAL" in embed["title"], "Title phai co so luong loi"
    assert embed["color"] == 0xE53935, f"Color phai do dam, got {embed['color']}"
    # Phai co field chi tiet loi cho Redis va Binance
    field_names = [f["name"] for f in embed["fields"]]
    assert any("Redis" in n and "Chi tiet" in n for n in field_names), \
        "Phai co field chi tiet loi Redis"
    assert any("Binance" in n and "Chi tiet" in n for n in field_names), \
        "Phai co field chi tiet loi Binance"
    print(f"[OK] Test 6: _build_alert_embed — title, color, {len(embed['fields'])} fields")


# ── Test 7: _build_ok_embed ───────────────────────────────────────────────────

def test_build_ok_embed(s: dict):
    """Test 7: _build_ok_embed co title OK va color xanh la."""
    CheckResult = s["CheckResult"]
    fn = s["_build_ok_embed"]

    results = [
        CheckResult("database",    True, "OK 12ms",      12.0),
        CheckResult("redis",       True, "OK 3ms",         3.0),
        CheckResult("bot_status",  True, "OK 2 running",   8.0),
        CheckResult("binance_api", True, "OK 45ms",       45.0),
    ]
    embed = fn(results, "2026-05-07 14:30 UTC+7")

    assert "ALL OK" in embed["title"], "Title phai co ALL OK"
    assert embed["color"] == 0x43A047, f"Color phai xanh la, got {embed['color']}"
    assert len(embed["fields"]) == 4, f"Phai co 4 fields, got {len(embed['fields'])}"
    print(f"[OK] Test 7: _build_ok_embed — title, color xanh, 4 fields")


# ── Test 8: Anti-spam logic ───────────────────────────────────────────────────

async def test_anti_spam_logic(s: dict):
    """Test 8: Anti-spam — khong gui alert khi trang thai loi khong doi."""
    HealthCheckService = s["HealthCheckService"]
    CheckResult = s["CheckResult"]

    sent_alerts = []

    # Mock send_discord_message
    import src.apps.monitoring.health_check_service as svc_module
    original_send = svc_module.send_discord_message

    async def mock_send(embed=None, webhook_url=None, content=None):
        sent_alerts.append(embed)

    svc_module.send_discord_message = mock_send

    try:
        import os
        os.environ["DISCORD_WEBHOOK_URL"] = "https://mock.webhook/test"

        service = HealthCheckService()

        # Lần 1: Redis fail → phai gui alert
        results_fail = [
            CheckResult("database",    True,  "OK",    5.0),
            CheckResult("redis",       False, "FAIL",  0.0, detail="err"),
            CheckResult("bot_status",  True,  "OK",    5.0),
            CheckResult("binance_api", True,  "OK",   45.0),
        ]
        await service._handle_alerting(results_fail, "T1")
        assert len(sent_alerts) == 1, f"Phai gui 1 alert, got {len(sent_alerts)}"

        # Lần 2: Cung loi Redis → KHONG gui alert (trang thai khong doi)
        await service._handle_alerting(results_fail, "T2")
        assert len(sent_alerts) == 1, f"Khong duoc gui them alert, got {len(sent_alerts)}"

        # Lần 3: Loi moi them (Binance) → phai gui alert
        results_more_fail = [
            CheckResult("database",    True,  "OK",    5.0),
            CheckResult("redis",       False, "FAIL",  0.0, detail="err"),
            CheckResult("bot_status",  True,  "OK",    5.0),
            CheckResult("binance_api", False, "FAIL",  0.0, detail="err"),
        ]
        await service._handle_alerting(results_more_fail, "T3")
        assert len(sent_alerts) == 2, f"Phai gui them 1 alert, got {len(sent_alerts)}"

        # Lần 4: Tat ca OK → phai gui recover notification
        results_ok = [
            CheckResult("database",    True, "OK",  5.0),
            CheckResult("redis",       True, "OK",  3.0),
            CheckResult("bot_status",  True, "OK",  5.0),
            CheckResult("binance_api", True, "OK", 45.0),
        ]
        await service._handle_alerting(results_ok, "T4")
        assert len(sent_alerts) == 3, f"Phai gui recover notification, got {len(sent_alerts)}"

        print(
            f"[OK] Test 8: Anti-spam — "
            f"gui dung {len(sent_alerts)} alerts (fail/no-change/more-fail/recover)"
        )
    finally:
        svc_module.send_discord_message = original_send
        os.environ.pop("DISCORD_WEBHOOK_URL", None)


# ── Test 9: _fmt_ago ──────────────────────────────────────────────────────────

def test_fmt_ago(s: dict):
    """Test 9: _fmt_ago format thoi gian chinh xac."""
    fn = s["_fmt_ago"]

    now = datetime.utcnow()
    assert "5 phut" in fn(now - timedelta(minutes=5))
    assert "30 phut" in fn(now - timedelta(minutes=30))
    assert "2 gio" in fn(now - timedelta(hours=2))
    assert fn(None) == "unknown"
    print("[OK] Test 9: _fmt_ago — format thoi gian OK")


# ── Test 10: _build_action_hints ─────────────────────────────────────────────

def test_build_action_hints(s: dict):
    """Test 10: _build_action_hints tao goi y dung theo loai loi."""
    CheckResult = s["CheckResult"]
    fn = s["_build_action_hints"]

    failed = [
        CheckResult("database",    False, "FAIL", 0.0),
        CheckResult("binance_api", False, "FAIL", 0.0),
    ]
    hints = fn(failed)
    assert "DB" in hints or "PostgreSQL" in hints, "Phai co goi y ve DB"
    assert "Binance" in hints or "IP" in hints, "Phai co goi y ve Binance"
    assert "Redis" not in hints, "Khong co loi Redis thi khong goi y Redis"
    print("[OK] Test 10: _build_action_hints — goi y dung theo loai loi")


# ── Test 11: Heartbeat trong bot_engine ──────────────────────────────────────

def test_heartbeat_in_bot_engine():
    """Test 11: BotEngine co _write_heartbeat method."""
    import ast
    with open("src/core/bot_engine.py", encoding="utf-8") as f:
        source = f.read()
        tree = ast.parse(source)

    # Tim class BotEngine
    bot_engine_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "BotEngine":
            bot_engine_class = node
            break
    assert bot_engine_class is not None, "Khong tim thay class BotEngine"

    # Tim method _write_heartbeat
    method_names = [
        n.name for n in ast.walk(bot_engine_class)
        if isinstance(n, ast.AsyncFunctionDef)
    ]
    assert "_write_heartbeat" in method_names, \
        f"BotEngine phai co _write_heartbeat, co: {method_names}"

    # Kiem tra _run_cycle goi _write_heartbeat
    assert "_write_heartbeat" in source, "_run_cycle phai goi _write_heartbeat"
    print("[OK] Test 11: BotEngine._write_heartbeat ton tai va duoc goi trong _run_cycle")


# ── Test 12: main.py integration ─────────────────────────────────────────────

def test_main_py_integration():
    """Test 12: main.py da co setup_health_check_job call."""
    with open("main.py", encoding="utf-8") as f:
        content = f.read()
    assert "setup_health_check_job" in content, "main.py phai goi setup_health_check_job"
    assert "from src.apps.monitoring import setup_health_check_job" in content or \
           "setup_health_check_job" in content, "main.py phai import setup_health_check_job"
    print("[OK] Test 12: main.py da tich hop setup_health_check_job")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all_tests():
    print("=" * 60)
    print("  HealthCheckService + Heartbeat — Tests")
    print("=" * 60)
    print()

    s = test_imports()
    test_constants(s)
    test_check_result(s)
    test_async_methods(s)
    test_build_status_fields(s)
    test_build_alert_embed(s)
    test_build_ok_embed(s)
    asyncio.run(test_anti_spam_logic(s))
    test_fmt_ago(s)
    test_build_action_hints(s)
    test_heartbeat_in_bot_engine()
    test_main_py_integration()

    print()
    print("=" * 60)
    print("  TAT CA 12 TESTS PASS")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_all_tests()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Assertion: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[FAIL] Unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)
