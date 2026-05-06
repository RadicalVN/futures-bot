"""
registry.py — SchedulerRegistry: Singleton quản lý BaseScheduler toàn cục.

Cung cấp một điểm truy cập duy nhất để:
- Khởi tạo scheduler khi app start (initialize)
- Đăng ký job từ bất kỳ module nào (register)
- Lấy instance để start/stop (get)

Pattern: Singleton — chỉ có 1 instance BaseScheduler trong toàn bộ process.
"""
import os

from loguru import logger

from src.core.scheduler.base_scheduler import BaseScheduler
from src.core.scheduler.job_config import JobConfig


class SchedulerRegistry:
    """Singleton registry cho BaseScheduler.

    Không khởi tạo trực tiếp. Dùng các class method:
        SchedulerRegistry.initialize(redis_url)  — gọi 1 lần khi app start
        SchedulerRegistry.get()                  — lấy instance
        SchedulerRegistry.register(config)       — đăng ký job

    Example:
        # main.py
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        SchedulerRegistry.initialize(redis_url)
        await SchedulerRegistry.get().start()

        # apps/monitoring/jobs.py
        from src.core.scheduler import SchedulerRegistry, JobConfig

        SchedulerRegistry.register(JobConfig(
            job_id="exit_monitor_bot_7",
            func=exit_monitor.run_once,
            trigger="interval",
            trigger_args={"seconds": 30},
            lock_ttl_seconds=25,
        ))
    """

    _instance: BaseScheduler | None = None

    @classmethod
    def initialize(cls, redis_url: str | None = None, redis_max_connections: int = 10) -> None:
        """Khởi tạo BaseScheduler singleton.

        Phải được gọi một lần duy nhất khi app start, trước khi
        bất kỳ module nào gọi register() hoặc get().

        Nếu gọi lại sau khi đã initialize, sẽ log warning và bỏ qua.

        Args:
            redis_url: Redis connection URL. Nếu None, đọc từ env REDIS_URL.
                Fallback về "redis://localhost:6379/0" nếu env cũng không có.
            redis_max_connections: Số connection tối đa trong Redis pool. Mặc định 10.
        """
        if cls._instance is not None:
            logger.warning(
                "[SchedulerRegistry] Đã được initialize trước đó — bỏ qua lần gọi này."
            )
            return

        resolved_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        cls._instance = BaseScheduler(
            redis_url=resolved_url,
            redis_max_connections=redis_max_connections,
        )
        logger.info(
            f"[SchedulerRegistry] Initialized | Redis: {resolved_url} "
            f"| max_connections={redis_max_connections}"
        )

    @classmethod
    def get(cls) -> BaseScheduler:
        """Lấy BaseScheduler instance.

        Returns:
            BaseScheduler instance đã được initialize.

        Raises:
            RuntimeError: Nếu initialize() chưa được gọi.
        """
        if cls._instance is None:
            raise RuntimeError(
                "[SchedulerRegistry] Chưa được initialize. "
                "Hãy gọi SchedulerRegistry.initialize() khi app start."
            )
        return cls._instance

    @classmethod
    def register(cls, config: JobConfig) -> None:
        """Đăng ký một job vào scheduler.

        Shortcut cho SchedulerRegistry.get().add_job(config).
        Có thể gọi trước khi scheduler.start() — job sẽ được đăng ký
        vào APScheduler và bắt đầu chạy sau khi start() được gọi.

        Args:
            config: Cấu hình đầy đủ của job.

        Raises:
            RuntimeError: Nếu initialize() chưa được gọi.
        """
        cls.get().add_job(config)

    @classmethod
    def reset(cls) -> None:
        """Reset singleton về None.

        Chỉ dùng trong unit test để tái khởi tạo giữa các test case.
        KHÔNG dùng trong production code.
        """
        cls._instance = None
