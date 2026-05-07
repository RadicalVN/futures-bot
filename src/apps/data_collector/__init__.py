# src/apps/data_collector — Data Collector Application
# Chịu trách nhiệm thu thập và cập nhật dữ liệu nến OHLCV từ Binance.
# Chạy độc lập — không phụ thuộc vào BotEngine hay apps khác.
# Giao tiếp với apps khác qua bảng ohlcv_candles trong DB.
#
# Public API:
#   setup_data_collector_job(scheduler) — đăng ký job vào SchedulerRegistry
from src.apps.data_collector.ohlcv_collector_service import setup_data_collector_job

__all__ = ["setup_data_collector_job"]
