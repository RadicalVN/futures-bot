"""
test_scheduler.py — Kiểm thử BaseScheduler và cơ chế Redis Lock.

Chạy: venv\\Scripts\\python.exe scripts/test_scheduler.py [--live]

Modes:
  (mặc định)  Mock Redis — chạy được mà không cần Redis server thực.
  --live       Live Redis — kết nối Redis thực tại REDIS_URL (hoặc localhost:6379).
               Dùng để verify Fencing Token và Lock TTL trên Redis thực.

Test cases:
  1.  JobConfig validation (valid + invalid inputs)
  2.  Retryable exception detection
  3.  Job thực thi đúng (mock Redis)
  4.  Redis Lock chống chồng chéo (mock Redis)
  5.  Fencing Token — không xóa lock của job khác (mock Redis)
  6.  Retry thành công sau N lần (mock Redis)
  7.  Retry hết lần — log error, không crash wrapper (mock Redis)
  8.  Non-retryable error — raise ngay, không retry (mock Redis)
  9.  SchedulerRegistry Singleton pattern
  10. Health Tracking — status OK sau khi job thành công
  11. Health Tracking — status FAILED + consecutive_failures tăng
  12. Health Tracking — status SKIPPED khi lock bị giữ
  13. Health Tracking — get_health_report() trả về JSON-serializable
  14. Redis Connection Pool — max_connections được set đúng
  15. [--live] Lock thực tế trên Redis: job 2 bị skip khi job 1 đang giữ lock
  16. [--live] Fencing Token thực tế: job cũ không xóa lock của job mới
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# ── Project root vào sys.path ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.core.scheduler.job_config import JobConfig
from src.core.scheduler.base_scheduler import (
    BaseScheduler, JobStatus, JobHealthRecord, _is_retryable
)
from src.core.scheduler.registry import SchedulerRegistry

# ── Helpers ───────────────────────────────────────────────────────────────────

_results: list[tuple[str, bool]] = []
_live_mode = "--live" in sys.argv


def check(name: str, condition: bool, detail: str = "") -> None:
    """Ghi nhận kết quả một test case."""
    status = "✅ PASS" if condition else "❌ FAIL"
    suffix = f" | {detail}" if detail else ""
    print(f"  {status}  {name}{suffix}")
    _results.append((name, condition))


def _make_mock_redis(acquire_ok: bool = True, release_ok: bool = True) -> AsyncMock:
    """Tạo mock Redis với hành vi acquire/release có thể cấu hình."""
    mock = AsyncMock()
    mock.set = AsyncMock(return_value=True if acquire_ok else None)
    mock.eval = AsyncMock(return_value=1 if release_ok else 0)
    mock.ping = AsyncMock(return_value=True)
    mock.aclose = AsyncMock()
    return mock


def _make_scheduler(mock_redis: AsyncMock) -> BaseScheduler:
    """Tạo BaseScheduler với mock Redis đã inject sẵn."""
    s = BaseScheduler(redis_url="redis://mock:6379/0")
    s._redis = mock_redis
    return s


# ── Test 1: JobConfig validation ──────────────────────────────────────────────

def test_job_config_validation() -> None:
    print("\n[Test 1] JobConfig validation")

    async def _noop() -> None:
        pass

    # Valid config đầy đủ
    try:
        cfg = JobConfig(
            job_id="my_job",
            func=_noop,
            trigger="interval",
            trigger_args={"seconds": 30},
            max_retries=3,
            retry_delay_seconds=5.0,
            lock_ttl_seconds=25,
        )
        check("Valid config tạo thành công", True)
        check("job_id đúng", cfg.job_id == "my_job")
        check("trigger đúng", cfg.trigger == "interval")
        check("enabled mặc định True", cfg.enabled is True)
        check("lock_ttl_seconds đúng", cfg.lock_ttl_seconds == 25)
    except Exception as e:
        check("Valid config tạo thành công", False, str(e))

    # job_id có khoảng trắng → ValueError
    try:
        JobConfig(job_id="job with spaces", func=_noop, trigger="interval", trigger_args={})
        check("job_id có khoảng trắng bị reject", False, "Không raise ValueError")
    except ValueError:
        check("job_id có khoảng trắng bị reject", True)

    # trigger không hợp lệ → ValueError
    try:
        JobConfig(job_id="j", func=_noop, trigger="unknown", trigger_args={})
        check("trigger không hợp lệ bị reject", False, "Không raise ValueError")
    except ValueError:
        check("trigger không hợp lệ bị reject", True)

    # enabled=False
    cfg_off = JobConfig(job_id="off_job", func=_noop, trigger="cron", trigger_args={}, enabled=False)
    check("enabled=False được set đúng", cfg_off.enabled is False)


# ── Test 2: Retryable exception detection ────────────────────────────────────

def test_retryable_detection() -> None:
    print("\n[Test 2] Retryable exception detection")

    check("ConnectionError là retryable", _is_retryable(ConnectionError()))
    check("TimeoutError là retryable", _is_retryable(TimeoutError()))
    check("asyncio.TimeoutError là retryable", _is_retryable(asyncio.TimeoutError()))
    check("OSError là retryable", _is_retryable(OSError()))
    check("ValueError KHÔNG retryable", not _is_retryable(ValueError()))
    check("KeyError KHÔNG retryable", not _is_retryable(KeyError()))
    check("RuntimeError KHÔNG retryable", not _is_retryable(RuntimeError()))
    check("Exception KHÔNG retryable", not _is_retryable(Exception()))


# ── Test 3: Job thực thi đúng ─────────────────────────────────────────────────

async def test_job_execution() -> None:
    print("\n[Test 3] Job thực thi đúng (mock Redis)")

    call_count = 0

    async def my_job() -> None:
        nonlocal call_count
        call_count += 1

    scheduler = _make_scheduler(_make_mock_redis(acquire_ok=True, release_ok=True))
    cfg = JobConfig(job_id="exec_test", func=my_job, trigger="interval", trigger_args={"seconds": 60})
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    await scheduler._job_wrapper(cfg)

    check("Job được gọi đúng 1 lần", call_count == 1, f"call_count={call_count}")
    check("Redis SET được gọi (acquire)", scheduler._redis.set.called)
    check("Redis eval được gọi (release)", scheduler._redis.eval.called)

    # Kiểm tra eval được gọi với đúng 1 key (numkeys=1)
    call_args = scheduler._redis.eval.call_args
    check("eval numkeys=1", call_args[0][1] == 1)


# ── Test 4: Redis Lock chống chồng chéo ──────────────────────────────────────

async def test_lock_prevents_overlap() -> None:
    print("\n[Test 4] Redis Lock chống chồng chéo (mock Redis)")

    call_count = 0

    async def slow_job() -> None:
        nonlocal call_count
        call_count += 1

    # SET NX trả về None → acquire thất bại (lock đang bị giữ)
    scheduler = _make_scheduler(_make_mock_redis(acquire_ok=False))
    cfg = JobConfig(job_id="overlap_test", func=slow_job, trigger="interval", trigger_args={"seconds": 60})
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    await scheduler._job_wrapper(cfg)

    check("Job KHÔNG được gọi khi lock đang bị giữ", call_count == 0, f"call_count={call_count}")
    check("Redis eval KHÔNG được gọi (không release lock người khác)", not scheduler._redis.eval.called)


# ── Test 5: Fencing Token — không xóa lock của job khác ──────────────────────

async def test_fencing_token_mock() -> None:
    print("\n[Test 5] Fencing Token safety (mock Redis)")

    async def _noop() -> None:
        pass

    # eval trả về 0 → token không khớp (lock đã bị job khác chiếm sau khi TTL hết)
    scheduler = _make_scheduler(_make_mock_redis(acquire_ok=True, release_ok=False))
    cfg = JobConfig(job_id="fencing_test", func=_noop, trigger="interval", trigger_args={"seconds": 60})
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    try:
        await scheduler._job_wrapper(cfg)
        check("Không raise exception khi token mismatch", True)
    except Exception as e:
        check("Không raise exception khi token mismatch", False, str(e))

    check("eval được gọi để thử release", scheduler._redis.eval.called)


# ── Test 6: Retry thành công sau N lần ───────────────────────────────────────

async def test_retry_success() -> None:
    print("\n[Test 6] Retry thành công sau N lần (mock Redis)")

    attempt = 0

    async def flaky_job() -> None:
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise ConnectionError("Simulated network error")

    scheduler = _make_scheduler(_make_mock_redis())
    cfg = JobConfig(
        job_id="retry_ok",
        func=flaky_job,
        trigger="interval",
        trigger_args={"seconds": 60},
        max_retries=3,
        retry_delay_seconds=0.01,
    )
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    await scheduler._job_wrapper(cfg)
    check("Job thành công sau 3 lần thử", attempt == 3, f"attempts={attempt}")


# ── Test 7: Retry hết lần — không crash wrapper ───────────────────────────────

async def test_retry_exhausted() -> None:
    print("\n[Test 7] Retry hết lần — log error, không crash wrapper (mock Redis)")

    call_count = 0

    async def always_fail() -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Always fails")

    scheduler = _make_scheduler(_make_mock_redis())
    cfg = JobConfig(
        job_id="retry_exhaust",
        func=always_fail,
        trigger="interval",
        trigger_args={"seconds": 60},
        max_retries=2,
        retry_delay_seconds=0.01,
    )
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    try:
        await scheduler._job_wrapper(cfg)
        check("Wrapper không crash khi hết retry", True)
    except Exception as e:
        check("Wrapper không crash khi hết retry", False, str(e))

    # max_retries=2 → 1 lần đầu + 2 lần retry = 3 lần gọi
    check("Gọi đúng max_retries+1 lần", call_count == 3, f"call_count={call_count}")


# ── Test 8: Non-retryable error — raise ngay ─────────────────────────────────

async def test_non_retryable_no_retry() -> None:
    print("\n[Test 8] Non-retryable error — raise ngay, không retry (mock Redis)")

    call_count = 0

    async def logic_error_job() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Logic error — không retry")

    scheduler = _make_scheduler(_make_mock_redis())
    cfg = JobConfig(
        job_id="non_retry",
        func=logic_error_job,
        trigger="interval",
        trigger_args={"seconds": 60},
        max_retries=5,
        retry_delay_seconds=0.01,
    )
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    await scheduler._job_wrapper(cfg)
    check("Chỉ gọi 1 lần (không retry)", call_count == 1, f"call_count={call_count}")


# ── Test 9: SchedulerRegistry Singleton ──────────────────────────────────────

def test_registry_singleton() -> None:
    print("\n[Test 9] SchedulerRegistry Singleton")

    SchedulerRegistry.reset()

    # get() trước initialize() → RuntimeError
    try:
        SchedulerRegistry.get()
        check("get() trước initialize() raise RuntimeError", False, "Không raise")
    except RuntimeError:
        check("get() trước initialize() raise RuntimeError", True)

    # initialize() lần đầu
    SchedulerRegistry.initialize("redis://localhost:6379/0", redis_max_connections=5)
    inst1 = SchedulerRegistry.get()
    check("initialize() tạo instance thành công", inst1 is not None)
    check("max_connections được set đúng", inst1._redis_max_connections == 5)

    # initialize() lần 2 → bỏ qua (singleton)
    SchedulerRegistry.initialize("redis://localhost:6379/99")
    inst2 = SchedulerRegistry.get()
    check("initialize() lần 2 bị bỏ qua (singleton)", inst1 is inst2)
    check("Redis URL giữ nguyên từ lần initialize đầu", inst1._redis_url == "redis://localhost:6379/0")

    SchedulerRegistry.reset()
    check("reset() xóa instance", SchedulerRegistry._instance is None)


# ── Test 10: Health Tracking — status OK ─────────────────────────────────────

async def test_health_tracking_ok() -> None:
    print("\n[Test 10] Health Tracking — status OK sau khi job thành công")

    async def good_job() -> None:
        pass

    scheduler = _make_scheduler(_make_mock_redis())
    cfg = JobConfig(job_id="health_ok", func=good_job, trigger="interval", trigger_args={"seconds": 60})
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    # Trạng thái ban đầu
    check("Status ban đầu là PENDING", scheduler._health[cfg.job_id].status == JobStatus.PENDING)

    await scheduler._job_wrapper(cfg)

    record = scheduler._health[cfg.job_id]
    check("Status chuyển sang OK", record.status == JobStatus.OK)
    check("last_run_at được set", record.last_run_at is not None)
    check("last_duration_ms được set", record.last_duration_ms is not None)
    check("last_error là None", record.last_error is None)
    check("consecutive_failures = 0", record.consecutive_failures == 0)
    check("total_runs = 1", record.total_runs == 1)
    check("total_failures = 0", record.total_failures == 0)


# ── Test 11: Health Tracking — status FAILED ─────────────────────────────────

async def test_health_tracking_failed() -> None:
    print("\n[Test 11] Health Tracking — status FAILED + consecutive_failures tăng")

    async def bad_job() -> None:
        raise ValueError("Intentional failure")

    scheduler = _make_scheduler(_make_mock_redis())
    cfg = JobConfig(
        job_id="health_fail",
        func=bad_job,
        trigger="interval",
        trigger_args={"seconds": 60},
        max_retries=0,
    )
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    # Chạy 2 lần để verify consecutive_failures tăng
    await scheduler._job_wrapper(cfg)
    await scheduler._job_wrapper(cfg)

    record = scheduler._health[cfg.job_id]
    check("Status chuyển sang FAILED", record.status == JobStatus.FAILED)
    check("last_error được set", record.last_error is not None)
    check("last_error chứa tên exception", "ValueError" in (record.last_error or ""))
    check("consecutive_failures = 2", record.consecutive_failures == 2, f"got={record.consecutive_failures}")
    check("total_runs = 2", record.total_runs == 2)
    check("total_failures = 2", record.total_failures == 2)

    # Sau khi thành công → consecutive_failures reset về 0
    async def good_job() -> None:
        pass

    cfg_ok = JobConfig(job_id="health_fail", func=good_job, trigger="interval", trigger_args={"seconds": 60})
    await scheduler._job_wrapper(cfg_ok)

    record_after = scheduler._health[cfg.job_id]
    check("consecutive_failures reset về 0 sau khi thành công", record_after.consecutive_failures == 0)
    check("total_failures vẫn là 2 (không reset)", record_after.total_failures == 2)


# ── Test 12: Health Tracking — status SKIPPED ────────────────────────────────

async def test_health_tracking_skipped() -> None:
    print("\n[Test 12] Health Tracking — status SKIPPED khi lock bị giữ")

    async def _noop() -> None:
        pass

    # Lock đang bị giữ → job bị skip
    scheduler = _make_scheduler(_make_mock_redis(acquire_ok=False))
    cfg = JobConfig(job_id="health_skip", func=_noop, trigger="interval", trigger_args={"seconds": 60})
    scheduler._health[cfg.job_id] = JobHealthRecord(job_id=cfg.job_id)

    await scheduler._job_wrapper(cfg)

    record = scheduler._health[cfg.job_id]
    check("Status chuyển sang SKIPPED", record.status == JobStatus.SKIPPED)
    check("total_runs KHÔNG tăng khi skip", record.total_runs == 0)

    # SKIPPED không override FAILED
    scheduler2 = _make_scheduler(_make_mock_redis(acquire_ok=False))
    cfg2 = JobConfig(job_id="health_skip2", func=_noop, trigger="interval", trigger_args={"seconds": 60})
    scheduler2._health[cfg2.job_id] = JobHealthRecord(
        job_id=cfg2.job_id,
        status=JobStatus.FAILED,
        consecutive_failures=3,
    )
    await scheduler2._job_wrapper(cfg2)
    check("SKIPPED không override FAILED", scheduler2._health[cfg2.job_id].status == JobStatus.FAILED)


# ── Test 13: get_health_report() JSON-serializable ───────────────────────────

async def test_health_report_format() -> None:
    print("\n[Test 13] get_health_report() trả về JSON-serializable")

    import json

    async def job_a() -> None:
        pass

    async def job_b() -> None:
        raise ValueError("fail")

    scheduler = _make_scheduler(_make_mock_redis())

    cfg_a = JobConfig(job_id="report_a", func=job_a, trigger="interval", trigger_args={"seconds": 60})
    cfg_b = JobConfig(job_id="report_b", func=job_b, trigger="interval", trigger_args={"seconds": 60}, max_retries=0)
    scheduler._health["report_a"] = JobHealthRecord(job_id="report_a")
    scheduler._health["report_b"] = JobHealthRecord(job_id="report_b")

    await scheduler._job_wrapper(cfg_a)
    await scheduler._job_wrapper(cfg_b)

    report = scheduler.get_health_report()

    check("get_health_report() trả về list", isinstance(report, list))
    check("Có đúng 2 records", len(report) == 2, f"got={len(report)}")

    # Kiểm tra JSON serializable
    try:
        json_str = json.dumps(report)
        check("Report JSON-serializable", True)
    except TypeError as e:
        check("Report JSON-serializable", False, str(e))

    # Kiểm tra các field bắt buộc
    required_fields = {
        "job_id", "status", "last_run_at", "last_duration_ms",
        "last_error", "consecutive_failures", "next_run_at",
        "total_runs", "total_failures"
    }
    record_a = next(r for r in report if r["job_id"] == "report_a")
    missing = required_fields - set(record_a.keys())
    check("Tất cả field bắt buộc có mặt", len(missing) == 0, f"missing={missing}")

    check("report_a status='ok'", record_a["status"] == "ok")
    check("report_b status='failed'", next(r for r in report if r["job_id"] == "report_b")["status"] == "failed")

    # last_run_at là ISO string (không phải datetime object)
    if record_a["last_run_at"] is not None:
        check("last_run_at là string ISO", isinstance(record_a["last_run_at"], str))


# ── Test 14: Redis Connection Pool ───────────────────────────────────────────

def test_redis_connection_pool() -> None:
    print("\n[Test 14] Redis Connection Pool — max_connections được set đúng")

    # Default max_connections
    s_default = BaseScheduler(redis_url="redis://localhost:6379/0")
    check("Default max_connections=10", s_default._redis_max_connections == 10)

    # Custom max_connections
    s_custom = BaseScheduler(redis_url="redis://localhost:6379/0", redis_max_connections=20)
    check("Custom max_connections=20", s_custom._redis_max_connections == 20)

    # SchedulerRegistry forward max_connections
    SchedulerRegistry.reset()
    SchedulerRegistry.initialize("redis://localhost:6379/0", redis_max_connections=15)
    inst = SchedulerRegistry.get()
    check("SchedulerRegistry forward max_connections=15", inst._redis_max_connections == 15)
    SchedulerRegistry.reset()


# ── Test 15 & 16: Live Redis tests ───────────────────────────────────────────

async def test_live_lock_prevents_overlap() -> None:
    """Test 15: Verify Redis Lock thực tế — job 2 bị skip khi job 1 đang giữ lock."""
    print("\n[Test 15] [LIVE] Redis Lock thực tế — job 2 bị skip")

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    job_id = "live_overlap_test"
    lock_key = f"scheduler:lock:{job_id}"

    s1 = BaseScheduler(redis_url=redis_url)
    s2 = BaseScheduler(redis_url=redis_url)

    try:
        await s1.start()
        await s2.start()
    except Exception as e:
        check("Kết nối Redis thành công", False, str(e))
        return

    check("Kết nối Redis thành công", True, redis_url)
    await s1._redis.delete(lock_key)

    s1_ran = False
    s2_ran = False
    s1_started = asyncio.Event()

    async def job_s1() -> None:
        nonlocal s1_ran
        s1_ran = True
        s1_started.set()
        await asyncio.sleep(0.5)

    async def job_s2() -> None:
        nonlocal s2_ran
        s2_ran = True

    cfg1 = JobConfig(job_id=job_id, func=job_s1, trigger="interval", trigger_args={"seconds": 60}, lock_ttl_seconds=5)
    cfg2 = JobConfig(job_id=job_id, func=job_s2, trigger="interval", trigger_args={"seconds": 60}, lock_ttl_seconds=5)
    s1._health[job_id] = JobHealthRecord(job_id=job_id)
    s2._health[job_id] = JobHealthRecord(job_id=job_id)

    async def run_s1() -> None:
        await s1._job_wrapper(cfg1)

    async def run_s2() -> None:
        await s1_started.wait()
        await s2._job_wrapper(cfg2)

    await asyncio.gather(run_s1(), run_s2())

    check("Job s1 đã chạy", s1_ran)
    check("Job s2 bị skip (lock đang bị s1 giữ)", not s2_ran)

    await s1._redis.delete(lock_key)
    await s1.stop()
    await s2.stop()


async def test_live_fencing_token() -> None:
    """Test 16: Verify Fencing Token thực tế — job cũ không xóa lock của job mới."""
    print("\n[Test 16] [LIVE] Fencing Token thực tế — job cũ không xóa lock của job mới")

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    job_id = "live_fencing_test"
    lock_key = f"scheduler:lock:{job_id}"

    s = BaseScheduler(redis_url=redis_url)
    try:
        await s.start()
    except Exception as e:
        check("Kết nối Redis thành công", False, str(e))
        return

    await s._redis.delete(lock_key)

    # Bước 1: Job cũ acquire lock với token_old
    token_old = "old-token-12345"
    await s._redis.set(lock_key, token_old, nx=True, ex=10)

    # Bước 2: Giả lập TTL hết → job mới acquire với token_new
    token_new = "new-token-67890"
    await s._redis.delete(lock_key)
    await s._redis.set(lock_key, token_new, nx=True, ex=10)

    # Bước 3: Job cũ cố release → phải thất bại (token mismatch)
    released = await s._release_lock(lock_key, token_old)
    check("Job cũ KHÔNG xóa được lock của job mới", not released)

    # Bước 4: Lock của job mới vẫn còn
    current_value = await s._redis.get(lock_key)
    check("Lock của job mới vẫn còn nguyên", current_value == token_new)

    # Bước 5: Job mới release đúng token → thành công
    released_new = await s._release_lock(lock_key, token_new)
    check("Job mới release đúng token → thành công", released_new)

    await s._redis.delete(lock_key)
    await s.stop()


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_async_tests() -> None:
    await test_job_execution()
    await test_lock_prevents_overlap()
    await test_fencing_token_mock()
    await test_retry_success()
    await test_retry_exhausted()
    await test_non_retryable_no_retry()
    await test_health_tracking_ok()
    await test_health_tracking_failed()
    await test_health_tracking_skipped()
    await test_health_report_format()

    if _live_mode:
        await test_live_lock_prevents_overlap()
        await test_live_fencing_token()


def main() -> None:
    print("=" * 60)
    print("  Scheduler Module — Test Suite")
    if _live_mode:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        print(f"  Mode: LIVE Redis ({redis_url})")
    else:
        print("  Mode: Mock Redis (dùng --live để test Redis thực)")
    print("=" * 60)

    test_job_config_validation()
    test_retryable_detection()
    asyncio.run(run_async_tests())
    test_registry_singleton()
    test_redis_connection_pool()

    print("\n" + "=" * 60)
    total = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    failed = total - passed
    print(f"  Kết quả: {passed}/{total} PASS | {failed} FAIL")
    print("=" * 60)

    if failed > 0:
        print("\nCác test FAIL:")
        for name, ok in _results:
            if not ok:
                print(f"  ❌  {name}")
        sys.exit(1)
    else:
        print("\n✅  Tất cả test PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
