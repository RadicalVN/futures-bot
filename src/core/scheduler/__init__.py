"""
src/core/scheduler — Bộ khung quản lý tác vụ nền tập trung.

Exports:
    BaseScheduler     — APScheduler wrapper với Redis Lock, Retry và Health Tracking.
    JobConfig         — Pydantic model mô tả cấu hình một Job.
    JobHealthRecord   — Pydantic model snapshot health của một Job (dùng cho Dashboard).
    JobStatus         — Enum trạng thái health: PENDING | OK | SKIPPED | FAILED.
    SchedulerRegistry — Singleton registry để đăng ký và lấy scheduler.
"""
from src.core.scheduler.job_config import JobConfig
from src.core.scheduler.base_scheduler import BaseScheduler, JobHealthRecord, JobStatus
from src.core.scheduler.registry import SchedulerRegistry

__all__ = [
    "JobConfig",
    "BaseScheduler",
    "JobHealthRecord",
    "JobStatus",
    "SchedulerRegistry",
]
