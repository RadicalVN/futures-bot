"""
base_scheduler.py — BaseScheduler: APScheduler + Redis Lock + Retry + Health Tracking.

Đây là lớp hạ tầng cốt lõi của bộ khung scheduler. Mọi job đều được
wrap qua _job_wrapper để đảm bảo:
  1. Chống chồng chéo (Redis Lock với Fencing Token)
  2. Tập trung Logging (start/end/error với duration)
  3. Retry tự động cho lỗi mạng/timeout
  4. Health Tracking in-memory (last_run, status, next_run, consecutive_failures)
"""
import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from pydantic import BaseModel

from src.core.scheduler.job_config import JobConfig


# ── Lua script: atomic check-and-delete cho Redis Lock ───────────────────────
# Chỉ DEL key nếu value khớp với token của job hiện tại.
# Điều này ngăn job cũ (chạy quá lâu, lock đã hết TTL) xóa nhầm
# lock của job mới đã acquire sau khi TTL hết.
_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# ── Các loại lỗi được phép retry ─────────────────────────────────────────────
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)

# Thử import httpx nếu có (dùng trong exchange calls)
try:
    import httpx
    _RETRYABLE_EXCEPTIONS = _RETRYABLE_EXCEPTIONS + (
        httpx.TimeoutException,
        httpx.NetworkError,
    )
except ImportError:
    pass

# ── Connection Pool defaults ──────────────────────────────────────────────────
_DEFAULT_REDIS_MAX_CONNECTIONS = 10


def _is_retryable(exc: Exception) -> bool:
    """Kiểm tra xem exception có thuộc loại retryable không.

    Args:
        exc: Exception cần kiểm tra.

    Returns:
        True nếu nên retry, False nếu là lỗi logic không thể retry.
    """
    return isinstance(exc, _RETRYABLE_EXCEPTIONS)


# ── Job Health Models ─────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    """Trạng thái health của một Job."""
    PENDING  = "pending"   # Đã đăng ký, chưa chạy lần nào
    OK       = "ok"        # Lần chạy gần nhất thành công
    SKIPPED  = "skipped"   # Bị skip do lock đang bị giữ (job khác đang chạy)
    FAILED   = "failed"    # Lần chạy gần nhất thất bại


class JobHealthRecord(BaseModel):
    """Snapshot health của một Job tại thời điểm hiện tại.

    Được lưu in-memory trong BaseScheduler và expose qua get_health_report().
    Không persist vào DB — đây là runtime state, reset khi restart.

    Attributes:
        job_id: ID duy nhất của job.
        status: Trạng thái lần chạy gần nhất.
        last_run_at: Thời điểm bắt đầu lần chạy gần nhất (UTC). None nếu chưa chạy.
        last_duration_ms: Duration của lần chạy gần nhất (ms). None nếu chưa chạy.
        last_error: Error message của lần thất bại gần nhất. None nếu OK.
        consecutive_failures: Số lần thất bại liên tiếp (reset về 0 khi thành công).
        next_run_at: Thời điểm dự kiến chạy tiếp theo (UTC). None nếu không xác định.
        total_runs: Tổng số lần đã chạy (không tính skip).
        total_failures: Tổng số lần thất bại từ khi khởi động.
    """
    job_id: str
    status: JobStatus = JobStatus.PENDING
    last_run_at: datetime | None = None
    last_duration_ms: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_run_at: datetime | None = None
    total_runs: int = 0
    total_failures: int = 0


class BaseScheduler:
    """
    Bộ khung quản lý Background Job với APScheduler, Redis Lock, Retry và Health Tracking.

    Mỗi job được wrap qua _job_wrapper để đảm bảo:
    - Chỉ 1 instance của job chạy tại một thời điểm (Redis Lock + Fencing Token).
    - Log đầy đủ: thời gian bắt đầu, kết thúc, duration, lỗi.
    - Retry tự động cho lỗi mạng/timeout (không retry lỗi logic).
    - Health record in-memory: last_run, status, next_run, consecutive_failures.

    Redis Connection Pool:
    - Dùng ConnectionPool với max_connections để tránh tạo quá nhiều connection.
    - Mặc định max_connections=10, đủ cho production nhỏ-vừa.

    Example:
        scheduler = BaseScheduler(redis_url="redis://localhost:6379/0")
        scheduler.add_job(JobConfig(
            job_id="my_job",
            func=my_async_func,
            trigger="interval",
            trigger_args={"seconds": 30},
        ))
        await scheduler.start()

        # Lấy health report cho Dashboard:
        report = scheduler.get_health_report()

        # Khi shutdown:
        await scheduler.stop()
    """

    def __init__(
        self,
        redis_url: str,
        redis_max_connections: int = _DEFAULT_REDIS_MAX_CONNECTIONS,
    ) -> None:
        """Khởi tạo scheduler với Redis connection pool.

        Args:
            redis_url: Redis connection URL. Ví dụ: "redis://localhost:6379/0".
            redis_max_connections: Số connection tối đa trong pool. Mặc định 10.
                Tăng lên nếu có nhiều job chạy đồng thời hoặc hệ thống scale lớn.
        """
        self._redis_url = redis_url
        self._redis_max_connections = redis_max_connections
        self._redis: aioredis.Redis | None = None
        self._apscheduler = AsyncIOScheduler(timezone="UTC")
        self._registered_jobs: dict[str, JobConfig] = {}
        self._health: dict[str, JobHealthRecord] = {}  # job_id → health record

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Kết nối Redis (với Connection Pool) và khởi động APScheduler.

        Raises:
            ConnectionError: Nếu không thể kết nối Redis.
        """
        pool = aioredis.ConnectionPool.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=self._redis_max_connections,
        )
        self._redis = aioredis.Redis(connection_pool=pool)

        # Ping để xác nhận kết nối Redis thành công
        await self._redis.ping()
        logger.info(
            f"[Scheduler] Redis connected: {self._redis_url} "
            f"| max_connections={self._redis_max_connections}"
        )

        self._apscheduler.start()
        logger.info(
            f"[Scheduler] Started. {len(self._registered_jobs)} job(s) registered."
        )

    async def stop(self) -> None:
        """Dừng APScheduler và đóng Redis connection pool."""
        self._apscheduler.shutdown(wait=False)
        if self._redis:
            await self._redis.aclose()
        logger.info("[Scheduler] Stopped.")

    # ── Job registration ──────────────────────────────────────────────────────

    def add_job(self, config: JobConfig) -> None:
        """Đăng ký một job vào scheduler.

        Job sẽ được wrap qua _job_wrapper để có Redis Lock, Logging và Retry.
        Nếu config.enabled=False, job sẽ bị bỏ qua.

        Args:
            config: Cấu hình đầy đủ của job.
        """
        if not config.enabled:
            logger.info(f"[Scheduler] Job '{config.job_id}' disabled — bỏ qua.")
            return

        if config.job_id in self._registered_jobs:
            logger.warning(
                f"[Scheduler] Job '{config.job_id}' đã được đăng ký trước đó — ghi đè."
            )

        self._registered_jobs[config.job_id] = config
        self._health[config.job_id] = JobHealthRecord(job_id=config.job_id)

        # Wrap func với _job_wrapper — closure capture config
        async def _wrapped() -> None:
            await self._job_wrapper(config)

        self._apscheduler.add_job(
            _wrapped,
            trigger=config.trigger,
            id=config.job_id,
            replace_existing=True,
            **config.trigger_args,
        )
        logger.info(
            f"[Scheduler] Job '{config.job_id}' registered "
            f"| trigger={config.trigger} {config.trigger_args} "
            f"| lock_ttl={config.lock_ttl_seconds}s "
            f"| max_retries={config.max_retries}"
        )

    def remove_job(self, job_id: str) -> None:
        """Gỡ bỏ một job khỏi scheduler.

        Args:
            job_id: ID của job cần gỡ bỏ.
        """
        self._registered_jobs.pop(job_id, None)
        self._health.pop(job_id, None)
        try:
            self._apscheduler.remove_job(job_id)
            logger.info(f"[Scheduler] Job '{job_id}' removed.")
        except Exception:
            logger.debug(f"[Scheduler] Job '{job_id}' không tồn tại khi remove.")

    # ── Health Report ─────────────────────────────────────────────────────────

    def get_health_report(self) -> list[dict[str, Any]]:
        """Trả về health report của tất cả job đã đăng ký.

        Được gọi bởi Dashboard API endpoint để hiển thị trạng thái job.
        Mỗi record bao gồm: job_id, status, last_run_at, last_duration_ms,
        last_error, consecutive_failures, next_run_at, total_runs, total_failures.

        Returns:
            List các dict (JSON-serializable) theo thứ tự đăng ký job.

        Example response:
            [
                {
                    "job_id": "exit_monitor_bot_7",
                    "status": "ok",
                    "last_run_at": "2026-05-07T10:00:00+00:00",
                    "last_duration_ms": 142.5,
                    "last_error": null,
                    "consecutive_failures": 0,
                    "next_run_at": "2026-05-07T10:00:30+00:00",
                    "total_runs": 120,
                    "total_failures": 2
                }
            ]
        """
        result = []
        for job_id, record in self._health.items():
            entry = record.model_dump()
            # Thêm next_run_at từ APScheduler (chính xác hơn in-memory estimate)
            entry["next_run_at"] = self._get_next_run_at(job_id)
            # Serialize datetime sang ISO string cho JSON
            for key in ("last_run_at", "next_run_at"):
                if entry[key] is not None:
                    entry[key] = entry[key].isoformat()
            result.append(entry)
        return result

    def _get_next_run_at(self, job_id: str) -> datetime | None:
        """Lấy thời điểm chạy tiếp theo từ APScheduler.

        Args:
            job_id: ID của job cần lấy next_run_at.

        Returns:
            datetime UTC của lần chạy tiếp theo, hoặc None nếu không xác định.
        """
        try:
            job = self._apscheduler.get_job(job_id)
            if job and job.next_run_time:
                return job.next_run_time.astimezone(timezone.utc)
        except Exception:
            pass
        return None

    # ── Core wrapper ──────────────────────────────────────────────────────────

    async def _job_wrapper(self, config: JobConfig) -> None:
        """Wrapper thực thi job với Lock, Logging, Retry và Health Tracking.

        Flow:
            1. Acquire Redis Lock (Fencing Token pattern)
            2. Log start + update health record
            3. Execute func() với retry loop
            4. Log end / error + update health record
            5. Release Redis Lock (chỉ xóa nếu token khớp)

        Args:
            config: Cấu hình của job cần thực thi.
        """
        lock_key = f"scheduler:lock:{config.job_id}"
        token = str(uuid.uuid4())  # Fencing token — duy nhất cho lần chạy này

        acquired = await self._acquire_lock(lock_key, token, config.lock_ttl_seconds)
        if not acquired:
            logger.warning(
                f"[Scheduler] Job '{config.job_id}' đang chạy (lock active) — bỏ qua lần này."
            )
            self._update_health_skipped(config.job_id)
            return

        start_time = datetime.now(timezone.utc)
        logger.info(
            f"[Scheduler] ▶ Job '{config.job_id}' bắt đầu lúc {start_time.strftime('%H:%M:%S UTC')}"
        )

        try:
            await self._execute_with_retry(config)
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            logger.info(
                f"[Scheduler] ✅ Job '{config.job_id}' hoàn thành "
                f"| duration={duration_ms:.0f}ms"
            )
            self._update_health_success(config.job_id, start_time, duration_ms)

        except Exception as exc:
            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                f"[Scheduler] ❌ Job '{config.job_id}' thất bại sau {duration_ms:.0f}ms "
                f"| {error_msg}\n{traceback.format_exc()}"
            )
            self._update_health_failure(config.job_id, start_time, duration_ms, error_msg)

        finally:
            # Chỉ release lock nếu token khớp (Fencing Token safety)
            released = await self._release_lock(lock_key, token)
            if not released:
                logger.warning(
                    f"[Scheduler] Job '{config.job_id}': lock đã hết TTL hoặc bị job khác chiếm "
                    f"— không release (token mismatch). Đây là dấu hiệu job chạy quá lâu."
                )

    async def _execute_with_retry(self, config: JobConfig) -> None:
        """Thực thi func() với cơ chế retry cho lỗi mạng/timeout.

        Chỉ retry khi exception thuộc _RETRYABLE_EXCEPTIONS.
        Lỗi logic (ValueError, KeyError, ...) sẽ raise ngay lập tức.

        Args:
            config: Cấu hình job chứa func, max_retries, retry_delay_seconds.

        Raises:
            Exception: Exception cuối cùng sau khi đã hết số lần retry.
        """
        last_exc: Exception | None = None

        for attempt in range(1, config.max_retries + 2):  # +2 vì attempt 1 là lần đầu
            try:
                await config.func()
                return  # Thành công — thoát khỏi retry loop
            except Exception as exc:
                if not _is_retryable(exc):
                    # Lỗi logic — không retry, raise ngay
                    raise

                last_exc = exc
                is_last_attempt = attempt > config.max_retries

                if is_last_attempt:
                    logger.error(
                        f"[Scheduler] Job '{config.job_id}': đã hết {config.max_retries} lần retry "
                        f"| Lỗi cuối: {type(exc).__name__}: {exc}"
                    )
                    raise last_exc

                logger.warning(
                    f"[Scheduler] Job '{config.job_id}': lỗi mạng lần {attempt} "
                    f"| {type(exc).__name__}: {exc} "
                    f"| Retry sau {config.retry_delay_seconds}s "
                    f"({attempt}/{config.max_retries})"
                )
                await asyncio.sleep(config.retry_delay_seconds)

    # ── Health update helpers ─────────────────────────────────────────────────

    def _update_health_success(
        self, job_id: str, start_time: datetime, duration_ms: float
    ) -> None:
        """Cập nhật health record sau khi job chạy thành công.

        Args:
            job_id: ID của job.
            start_time: Thời điểm bắt đầu chạy (UTC).
            duration_ms: Duration thực thi (ms).
        """
        record = self._health.get(job_id)
        if not record:
            return
        record.status = JobStatus.OK
        record.last_run_at = start_time
        record.last_duration_ms = duration_ms
        record.last_error = None
        record.consecutive_failures = 0
        record.total_runs += 1

    def _update_health_failure(
        self, job_id: str, start_time: datetime, duration_ms: float, error_msg: str
    ) -> None:
        """Cập nhật health record sau khi job thất bại.

        Args:
            job_id: ID của job.
            start_time: Thời điểm bắt đầu chạy (UTC).
            duration_ms: Duration thực thi (ms).
            error_msg: Mô tả lỗi ngắn gọn.
        """
        record = self._health.get(job_id)
        if not record:
            return
        record.status = JobStatus.FAILED
        record.last_run_at = start_time
        record.last_duration_ms = duration_ms
        record.last_error = error_msg[:500]  # Giới hạn độ dài để tránh bloat
        record.consecutive_failures += 1
        record.total_runs += 1
        record.total_failures += 1

    def _update_health_skipped(self, job_id: str) -> None:
        """Cập nhật health record khi job bị skip do lock đang bị giữ.

        Không tăng total_runs vì job không thực sự chạy.

        Args:
            job_id: ID của job.
        """
        record = self._health.get(job_id)
        if not record:
            return
        # Chỉ cập nhật status nếu job đang OK (không override FAILED bằng SKIPPED)
        if record.status in (JobStatus.PENDING, JobStatus.OK):
            record.status = JobStatus.SKIPPED

    # ── Redis Lock helpers ────────────────────────────────────────────────────

    async def _acquire_lock(
        self, lock_key: str, token: str, ttl_seconds: int
    ) -> bool:
        """Acquire Redis lock với Fencing Token.

        Dùng SET NX EX để đảm bảo atomic acquire.
        Value là token UUID duy nhất — dùng để verify khi release.

        Args:
            lock_key: Redis key của lock.
            token: UUID duy nhất cho lần chạy này (Fencing Token).
            ttl_seconds: TTL của lock (giây).

        Returns:
            True nếu acquire thành công, False nếu lock đang bị giữ.
        """
        if not self._redis:
            # Redis chưa kết nối — fallback: cho phép chạy (không có lock protection)
            logger.warning(
                f"[Scheduler] Redis chưa kết nối — job '{lock_key}' chạy không có lock."
            )
            return True

        result = await self._redis.set(
            lock_key,
            token,
            nx=True,    # Only set if Not eXists
            ex=ttl_seconds,
        )
        return result is not None  # SET NX trả về None nếu key đã tồn tại

    async def _release_lock(self, lock_key: str, token: str) -> bool:
        """Release Redis lock — chỉ xóa nếu token khớp (Fencing Token safety).

        Dùng Lua script để đảm bảo atomic check-and-delete.
        Nếu lock đã hết TTL và bị job khác chiếm (token khác),
        script sẽ trả về 0 và KHÔNG xóa lock của job mới.

        Args:
            lock_key: Redis key của lock.
            token: UUID của lần chạy hiện tại — phải khớp với value trong Redis.

        Returns:
            True nếu release thành công (token khớp và đã DEL).
            False nếu token không khớp (lock đã bị job khác chiếm).
        """
        if not self._redis:
            return True  # Không có Redis — coi như release thành công

        try:
            result = await self._redis.eval(
                _RELEASE_LOCK_SCRIPT,
                1,          # numkeys
                lock_key,   # KEYS[1]
                token,      # ARGV[1]
            )
            return bool(result)
        except Exception as exc:
            logger.warning(
                f"[Scheduler] Lỗi khi release lock '{lock_key}': {exc} — bỏ qua."
            )
            return False

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def registered_job_ids(self) -> list[str]:
        """Danh sách ID của các job đã đăng ký.

        Returns:
            List các job_id theo thứ tự đăng ký.
        """
        return list(self._registered_jobs.keys())

    def is_running(self) -> bool:
        """Kiểm tra scheduler có đang chạy không.

        Returns:
            True nếu APScheduler đang running.
        """
        return self._apscheduler.running
