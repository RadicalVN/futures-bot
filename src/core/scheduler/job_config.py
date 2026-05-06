"""
job_config.py — Pydantic model mô tả cấu hình của một Background Job.

Mỗi job được định nghĩa hoàn toàn qua JobConfig trước khi đăng ký
vào BaseScheduler. Điều này đảm bảo tính tường minh và dễ kiểm tra.
"""
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field, field_validator


class JobConfig(BaseModel):
    """Cấu hình đầy đủ cho một Background Job.

    Attributes:
        job_id: ID duy nhất của job. Dùng làm Redis lock key và APScheduler job ID.
            Phải là string hợp lệ, không chứa khoảng trắng.
        func: Async callable sẽ được thực thi. Phải là coroutine function.
        trigger: Loại trigger của APScheduler. Hỗ trợ "interval", "cron", "date".
        trigger_args: Tham số cho trigger.
            - interval: {"seconds": 30} hoặc {"minutes": 5}
            - cron:     {"hour": 0, "minute": 30}
            - date:     {"run_date": "2026-01-01 00:00:00"}
        max_retries: Số lần retry tối đa khi gặp lỗi mạng/timeout. Mặc định 3.
        retry_delay_seconds: Thời gian chờ (giây) giữa các lần retry. Mặc định 5.0.
        lock_ttl_seconds: TTL (giây) của Redis lock. Nên đặt nhỏ hơn interval
            để tránh lock bị giữ quá lâu khi job crash. Mặc định 55.
        enabled: Nếu False, job sẽ không được đăng ký vào scheduler. Mặc định True.
    """

    model_config = {"arbitrary_types_allowed": True}

    job_id: str = Field(..., description="ID duy nhất của job, không chứa khoảng trắng")
    func: Callable[..., Coroutine[Any, Any, None]] = Field(
        ..., description="Async function sẽ được thực thi"
    )
    trigger: str = Field(
        ..., description='Loại trigger: "interval" | "cron" | "date"'
    )
    trigger_args: dict[str, Any] = Field(
        ..., description="Tham số cho trigger (seconds, minutes, hour, minute, ...)"
    )
    max_retries: int = Field(
        default=3, ge=0, description="Số lần retry tối đa khi gặp lỗi retryable"
    )
    retry_delay_seconds: float = Field(
        default=5.0, gt=0, description="Thời gian chờ giữa các lần retry (giây)"
    )
    lock_ttl_seconds: int = Field(
        default=55, gt=0, description="TTL của Redis lock (giây)"
    )
    enabled: bool = Field(
        default=True, description="Nếu False, job sẽ không được đăng ký"
    )

    @field_validator("job_id")
    @classmethod
    def _validate_job_id(cls, v: str) -> str:
        """Đảm bảo job_id không chứa khoảng trắng (dùng làm Redis key)."""
        if " " in v:
            raise ValueError(f"job_id không được chứa khoảng trắng: '{v}'")
        if not v:
            raise ValueError("job_id không được rỗng")
        return v

    @field_validator("trigger")
    @classmethod
    def _validate_trigger(cls, v: str) -> str:
        """Đảm bảo trigger là một trong các giá trị hợp lệ."""
        allowed = {"interval", "cron", "date"}
        if v not in allowed:
            raise ValueError(f"trigger phải là một trong {allowed}, nhận được: '{v}'")
        return v
