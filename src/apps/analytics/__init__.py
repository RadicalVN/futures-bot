"""
analytics — Performance Analytics App.

Standalone module: chi doc tu src.database va src.core.
Khong import tu bat ky app nao khac (monitoring, dashboard, ...).

Public exports:
    setup_analytics_job  — Dang ky weekly report job vao SchedulerRegistry
    get_bot_performance  — Lay metrics cua 1 bot
    get_strategy_performance — Lay metrics cua 1 strategy
    get_all_bots_performance — Lay metrics cua tat ca bot
"""
from src.apps.analytics.service import (
    get_bot_performance,
    get_strategy_performance,
    get_all_bots_performance,
    setup_analytics_job,
)

__all__ = [
    "get_bot_performance",
    "get_strategy_performance",
    "get_all_bots_performance",
    "setup_analytics_job",
]
