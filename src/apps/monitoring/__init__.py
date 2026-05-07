# src/apps/monitoring — Monitoring Application
# Chịu trách nhiệm quét và đóng các lệnh đang mở (Exit Monitor)
# và giám sát trạng thái hệ thống (Health Check).
# Chạy độc lập với BotEngine — không phụ thuộc vào bất kỳ BotEngine instance nào.
#
# Public API:
#   setup_exit_monitor_job(scheduler)  — đăng ký exit monitor job
#   setup_health_check_job(scheduler)  — đăng ký health check job
from src.apps.monitoring.exit_monitor_service import setup_exit_monitor_job
from src.apps.monitoring.health_check_service import setup_health_check_job

__all__ = ["setup_exit_monitor_job", "setup_health_check_job"]
