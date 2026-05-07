# src/apps/monitoring — Monitoring Application
# Chịu trách nhiệm quét và đóng các lệnh đang mở (Exit Monitor).
# Chạy độc lập với BotEngine — không phụ thuộc vào bất kỳ BotEngine instance nào.
#
# Public API:
#   setup_exit_monitor_job(scheduler) — đăng ký job vào SchedulerRegistry
from src.apps.monitoring.exit_monitor_service import setup_exit_monitor_job

__all__ = ["setup_exit_monitor_job"]
