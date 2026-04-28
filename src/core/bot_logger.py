"""
bot_logger.py — Per-bot logging với tách file theo ngày

Mỗi bot có logger riêng ghi vào:
    logs/bot_{id}_{name}/YYYY-MM-DD.log

Dùng loguru sink động để tạo file mới mỗi ngày tự động.
"""
import re
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger as _root_logger


def _sanitize_name(name: str) -> str:
    """Chuyển tên bot thành tên folder hợp lệ (bỏ ký tự đặc biệt)."""
    return re.sub(r"[^\w\-]", "_", name).strip("_")


class BotLogger:
    """
    Logger riêng cho từng BotEngine.
    Ghi log vào logs/bot_{id}_{slug}/ với rotation theo ngày.
    Đồng thời forward lên root logger (stdout + trading.log chung).
    """

    def __init__(self, bot_id: int, bot_name: str):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self._slug = _sanitize_name(bot_name)
        self._log_dir = Path("logs") / f"bot_{bot_id}_{self._slug}"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._sink_id = None
        self._setup_sink()

    def _setup_sink(self):
        """Đăng ký sink loguru ghi vào file tách theo ngày."""
        log_path = self._log_dir / "{time:YYYY-MM-DD}.log"
        self._sink_id = _root_logger.add(
            str(log_path),
            rotation="00:00",          # Tách file lúc nửa đêm
            retention="30 days",       # Giữ 30 ngày
            compression="zip",         # Nén file cũ
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            level="DEBUG",
            encoding="utf-8",
            filter=lambda record: record["extra"].get("bot_id") == self.bot_id,
        )

    def remove(self):
        """Gỡ sink khi bot dừng."""
        if self._sink_id is not None:
            try:
                _root_logger.remove(self._sink_id)
            except Exception:
                pass
            self._sink_id = None

    def _bound(self):
        """Trả về logger đã bind bot_id để filter đúng sink."""
        return _root_logger.bind(bot_id=self.bot_id)

    # ── Public API ────────────────────────────────────────────────

    def debug(self, msg: str, *args, **kwargs):
        self._bound().debug(f"[Bot#{self.bot_id}] {msg}", *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._bound().info(f"[Bot#{self.bot_id}] {msg}", *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._bound().warning(f"[Bot#{self.bot_id}] {msg}", *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._bound().error(f"[Bot#{self.bot_id}] {msg}", *args, **kwargs)

    def success(self, msg: str, *args, **kwargs):
        self._bound().success(f"[Bot#{self.bot_id}] {msg}", *args, **kwargs)
