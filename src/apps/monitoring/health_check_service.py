"""
health_check_service.py — Giám sát trạng thái hệ thống tự động.

Chạy mỗi 5 phút, kiểm tra 4 checkpoint và gửi Discord alert ngay khi
phát hiện sự cố. Mỗi checkpoint độc lập — 1 lỗi không ảnh hưởng checkpoint khác.

Checkpoints:
    1. Database  — SELECT 1 để xác nhận PostgreSQL còn sống.
    2. Redis     — ping() để xác nhận Scheduler lock vẫn hoạt động.
    3. Bot Status — phát hiện bot running nhưng không gửi heartbeat > 10 phút.
    4. Binance API — GET /fapi/v1/ping để xác nhận không bị chặn IP.

Anti-spam:
    - Lỗi: gửi alert ngay, chỉ gửi lại khi trạng thái thay đổi.
    - OK:  gửi summary 1 lần/giờ (không spam mỗi 5 phút khi healthy).
    - State lưu in-memory trong service instance — reset khi restart.
"""
import asyncio
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from loguru import logger
from sqlalchemy import select, text

from src.core.discord_notifier import send_discord_message
from src.core.scheduler import JobConfig, SchedulerRegistry
from src.database.db import AsyncSessionLocal
from src.database.models import Bot

# ── Hằng số cấu hình ─────────────────────────────────────────────────────────

_SCAN_INTERVAL_SECONDS: int = 300
"""Tần suất chạy health check (giây). 5 phút."""

_LOCK_TTL_SECONDS: int = 270
"""TTL Redis lock — nhỏ hơn interval để tránh overlap."""

_JOB_ID: str = "health_check"
"""ID duy nhất của job trong SchedulerRegistry."""

_DB_TIMEOUT_SECONDS: float = 5.0
"""Timeout cho DB check (giây)."""

_REDIS_TIMEOUT_SECONDS: float = 3.0
"""Timeout cho Redis ping (giây)."""

_BINANCE_TIMEOUT_SECONDS: float = 5.0
"""Timeout cho Binance API check (giây)."""

_BOT_HEARTBEAT_THRESHOLD_MINUTES: int = 10
"""Bot bị coi là treo nếu updated_at cũ hơn N phút."""

_OK_SUMMARY_INTERVAL_HOURS: int = 1
"""Gửi summary OK tối đa 1 lần mỗi N giờ (tránh spam khi healthy)."""

_BINANCE_PING_URL: str = "https://fapi.binance.com/fapi/v1/ping"
"""Binance Futures public ping endpoint — không cần auth, không rate limit."""

UTC7 = timezone(timedelta(hours=7))


# ── CheckResult dataclass ─────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Kết quả của 1 checkpoint health check.

    Attributes:
        name: Tên checkpoint ("database" | "redis" | "bot_status" | "binance_api").
        ok: True nếu checkpoint healthy.
        message: Mô tả ngắn gọn kết quả (vd: "OK 12ms" hoặc "FAILED").
        latency_ms: Thời gian thực thi checkpoint (ms).
        detail: Chi tiết lỗi nếu ok=False (stacktrace ngắn, tên exception).
        extra: Thông tin bổ sung tùy checkpoint (vd: danh sách bot bị treo).
    """
    name:       str
    ok:         bool
    message:    str
    latency_ms: float
    detail:     str = ""
    extra:      str = ""


# ── Individual checkpoint functions ──────────────────────────────────────────

async def _check_database() -> CheckResult:
    """Kiểm tra kết nối PostgreSQL bằng SELECT 1.

    Dùng asyncio.wait_for để đảm bảo timeout cứng — không bị block vô hạn
    khi DB quá tải hoặc mạng bị treo.

    Returns:
        CheckResult với latency_ms và detail nếu lỗi.
    """
    t0 = _now_ms()

    async def _do_query() -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_do_query(), timeout=_DB_TIMEOUT_SECONDS)
        ms = _now_ms() - t0
        return CheckResult(
            name="database",
            ok=True,
            message=f"OK {ms:.0f}ms",
            latency_ms=ms,
        )
    except asyncio.TimeoutError:
        ms = _now_ms() - t0
        return CheckResult(
            name="database",
            ok=False,
            message=f"TIMEOUT >{_DB_TIMEOUT_SECONDS:.0f}s",
            latency_ms=ms,
            detail=f"SELECT 1 khong phan hoi sau {_DB_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        ms = _now_ms() - t0
        return CheckResult(
            name="database",
            ok=False,
            message="FAILED",
            latency_ms=ms,
            detail=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


async def _check_redis() -> CheckResult:
    """Kiểm tra Redis bằng ping() qua SchedulerRegistry.

    Dùng asyncio.wait_for để đảm bảo timeout cứng.
    Dùng Redis instance của scheduler để kiểm tra đúng connection pool
    mà các job đang dùng để acquire lock.

    Returns:
        CheckResult với latency_ms và detail nếu lỗi.
    """
    t0 = _now_ms()
    try:
        scheduler = SchedulerRegistry.get()
        redis = scheduler._redis
        if redis is None:
            return CheckResult(
                name="redis",
                ok=False,
                message="NOT CONNECTED",
                latency_ms=_now_ms() - t0,
                detail="Scheduler Redis chua duoc ket noi (scheduler chua start?)",
            )

        await asyncio.wait_for(redis.ping(), timeout=_REDIS_TIMEOUT_SECONDS)
        ms = _now_ms() - t0
        return CheckResult(
            name="redis",
            ok=True,
            message=f"OK {ms:.0f}ms",
            latency_ms=ms,
        )
    except asyncio.TimeoutError:
        ms = _now_ms() - t0
        return CheckResult(
            name="redis",
            ok=False,
            message=f"TIMEOUT >{_REDIS_TIMEOUT_SECONDS:.0f}s",
            latency_ms=ms,
            detail=f"Redis ping khong phan hoi sau {_REDIS_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        ms = _now_ms() - t0
        return CheckResult(
            name="redis",
            ok=False,
            message="FAILED",
            latency_ms=ms,
            detail=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


async def _check_bot_status() -> CheckResult:
    """Phát hiện bot running nhưng không gửi heartbeat trong _BOT_HEARTBEAT_THRESHOLD_MINUTES.

    Bot được coi là "treo" khi:
        status = 'running' AND updated_at < now() - threshold

    Heartbeat được ghi bởi BotEngine._write_heartbeat() cuối mỗi _run_cycle.
    Dùng asyncio.wait_for để đảm bảo timeout cứng cho DB query.

    Returns:
        CheckResult. ok=False nếu có ít nhất 1 bot treo.
        extra chứa danh sách bot bị treo để hiển thị trong alert.
    """
    t0 = _now_ms()

    async def _do_query() -> tuple[list, list]:
        threshold = datetime.utcnow() - timedelta(minutes=_BOT_HEARTBEAT_THRESHOLD_MINUTES)
        async with AsyncSessionLocal() as session:
            stale_result = await session.execute(
                select(Bot).where(
                    Bot.status == "running",
                    Bot.is_deleted == False,  # noqa: E711
                    Bot.updated_at < threshold,
                )
            )
            stale = stale_result.scalars().all()

            running_result = await session.execute(
                select(Bot).where(
                    Bot.status == "running",
                    Bot.is_deleted == False,  # noqa: E711
                )
            )
            running = running_result.scalars().all()
        return stale, running

    try:
        stale_bots, running_bots = await asyncio.wait_for(
            _do_query(), timeout=_DB_TIMEOUT_SECONDS
        )
        ms = _now_ms() - t0
        running_count = len(running_bots)

        if stale_bots:
            stale_names = ", ".join(
                f"#{b.id} {b.name} (last: {_fmt_ago(b.updated_at)})"
                for b in stale_bots
            )
            return CheckResult(
                name="bot_status",
                ok=False,
                message=f"STALE {len(stale_bots)}/{running_count} bots",
                latency_ms=ms,
                detail=(
                    f"{len(stale_bots)} bot khong heartbeat "
                    f"> {_BOT_HEARTBEAT_THRESHOLD_MINUTES}min"
                ),
                extra=stale_names,
            )

        return CheckResult(
            name="bot_status",
            ok=True,
            message=f"OK {running_count} running",
            latency_ms=ms,
        )
    except asyncio.TimeoutError:
        ms = _now_ms() - t0
        return CheckResult(
            name="bot_status",
            ok=False,
            message=f"TIMEOUT >{_DB_TIMEOUT_SECONDS:.0f}s",
            latency_ms=ms,
            detail=f"Bot status query khong phan hoi sau {_DB_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        ms = _now_ms() - t0
        return CheckResult(
            name="bot_status",
            ok=False,
            message="FAILED",
            latency_ms=ms,
            detail=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


async def _check_binance_api() -> CheckResult:
    """Kiểm tra kết nối Binance Futures public endpoint.

    Dùng GET /fapi/v1/ping — không cần auth, không rate limit.
    Dùng asyncio.wait_for để đảm bảo timeout cứng (không phụ thuộc aiohttp timeout).
    Phân biệt được "bị chặn IP" vs "mạng nội bộ lỗi".

    Returns:
        CheckResult với latency_ms và HTTP status code nếu lỗi.
    """
    t0 = _now_ms()

    async def _do_request() -> tuple[int, str]:
        """Thực hiện HTTP GET và trả về (status_code, body)."""
        async with aiohttp.ClientSession() as session:
            async with session.get(_BINANCE_PING_URL) as resp:
                body = await resp.text()
                return resp.status, body

    try:
        status_code, body = await asyncio.wait_for(
            _do_request(), timeout=_BINANCE_TIMEOUT_SECONDS
        )
        ms = _now_ms() - t0
        if status_code == 200:
            return CheckResult(
                name="binance_api",
                ok=True,
                message=f"OK {ms:.0f}ms",
                latency_ms=ms,
            )
        return CheckResult(
            name="binance_api",
            ok=False,
            message=f"HTTP {status_code}",
            latency_ms=ms,
            detail=f"HTTP {status_code}: {body[:200]}",
        )
    except asyncio.TimeoutError:
        ms = _now_ms() - t0
        return CheckResult(
            name="binance_api",
            ok=False,
            message=f"TIMEOUT >{_BINANCE_TIMEOUT_SECONDS:.0f}s",
            latency_ms=ms,
            detail=f"Binance ping khong phan hoi sau {_BINANCE_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        ms = _now_ms() - t0
        return CheckResult(
            name="binance_api",
            ok=False,
            message="FAILED",
            latency_ms=ms,
            detail=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


# ── Discord embed builders ────────────────────────────────────────────────────

def _build_alert_embed(results: list[CheckResult], checked_at: str) -> dict:
    """Tạo Discord embed cho trường hợp có checkpoint thất bại.

    Thiết kế cho mobile: emoji prefix, 2 cột inline, error detail riêng.

    Args:
        results: Danh sách 4 CheckResult.
        checked_at: Thời gian kiểm tra dạng string (UTC+7).

    Returns:
        Discord embed dict.
    """
    failed = [r for r in results if not r.ok]
    fields = _build_status_fields(results)

    # Thêm field chi tiết lỗi cho từng checkpoint thất bại
    for r in failed:
        error_text = f"`{r.detail}`" if r.detail else "_Khong co chi tiet_"
        if r.extra:
            error_text += f"\n```{r.extra[:300]}```"
        fields.append({
            "name": f"❌ {_checkpoint_label(r.name)} — Chi tiet loi",
            "value": error_text[:1024],
            "inline": False,
        })

    # Gợi ý hành động theo loại lỗi
    hints = _build_action_hints(failed)
    if hints:
        fields.append({
            "name": "⚡ Hanh dong khuyen nghi",
            "value": hints,
            "inline": False,
        })

    return {
        "title": f"🚨 SYSTEM ALERT — {len(failed)} CRITICAL",
        "color": 0xE53935,  # Đỏ đậm
        "fields": fields,
        "footer": {"text": f"Trading Bot — Health Check | {checked_at}"},
        "timestamp": _utc_now_iso(),
    }


def _build_ok_embed(results: list[CheckResult], checked_at: str) -> dict:
    """Tạo Discord embed cho trường hợp tất cả checkpoint healthy.

    Args:
        results: Danh sách 4 CheckResult (tất cả ok=True).
        checked_at: Thời gian kiểm tra dạng string (UTC+7).

    Returns:
        Discord embed dict.
    """
    fields = _build_status_fields(results)
    return {
        "title": "✅ System Health — ALL OK",
        "color": 0x43A047,  # Xanh lá
        "fields": fields,
        "footer": {"text": f"Trading Bot — Health Check | {checked_at}"},
        "timestamp": _utc_now_iso(),
    }


def _build_status_fields(results: list[CheckResult]) -> list[dict]:
    """Tạo 4 field inline hiển thị trạng thái từng checkpoint.

    Dùng inline=True để hiển thị 2 cột trên mobile — dễ scan bằng mắt.

    Args:
        results: Danh sách CheckResult.

    Returns:
        List Discord field dict.
    """
    icons = {
        "database":   "🗄️",
        "redis":      "🔴",
        "bot_status": "🤖",
        "binance_api": "🌐",
    }
    fields = []
    for r in results:
        icon   = icons.get(r.name, "❓")
        status = "✅" if r.ok else "❌"
        fields.append({
            "name":   f"{icon} {_checkpoint_label(r.name)}",
            "value":  f"{status}  {r.message}",
            "inline": True,
        })
    return fields


def _build_action_hints(failed: list[CheckResult]) -> str:
    """Tạo gợi ý hành động dựa trên checkpoint thất bại.

    Args:
        failed: Danh sách CheckResult có ok=False.

    Returns:
        String gợi ý, hoặc rỗng nếu không có gợi ý.
    """
    hints = []
    names = {r.name for r in failed}
    if "database" in names:
        hints.append("• DB: Kiem tra PostgreSQL service va DATABASE_URL")
    if "redis" in names:
        hints.append("• Redis: Kiem tra Redis service va REDIS_URL")
    if "bot_status" in names:
        hints.append("• Bot: Kiem tra log bot, co the BotEngine bi treo")
    if "binance_api" in names:
        hints.append("• Binance: Kiem tra ket noi mang, IP co the bi block")
    return "\n".join(hints)


def _checkpoint_label(name: str) -> str:
    """Chuyển tên checkpoint sang label hiển thị.

    Args:
        name: Tên checkpoint nội bộ.

    Returns:
        Label thân thiện.
    """
    labels = {
        "database":    "Database",
        "redis":       "Redis",
        "bot_status":  "Bot Status",
        "binance_api": "Binance API",
    }
    return labels.get(name, name.title())


# ── Utility helpers ───────────────────────────────────────────────────────────

def _now_ms() -> float:
    """Trả về timestamp hiện tại tính bằng milliseconds."""
    return datetime.now(timezone.utc).timestamp() * 1000


def _utc_now_iso() -> str:
    """Trả về ISO string UTC hiện tại."""
    return datetime.now(timezone.utc).isoformat()


def _fmt_ago(dt: Optional[datetime]) -> str:
    """Format thời gian 'X phút trước' từ datetime UTC naive.

    Args:
        dt: datetime UTC naive (từ DB). None → "unknown".

    Returns:
        String dạng "5 phut truoc" hoặc "unknown".
    """
    if dt is None:
        return "unknown"
    delta = datetime.utcnow() - dt
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes} phut truoc"
    hours = minutes // 60
    return f"{hours} gio truoc"


def _now_utc7_str() -> str:
    """Trả về thời gian hiện tại dạng string UTC+7."""
    return datetime.now(UTC7).strftime("%Y-%m-%d %H:%M UTC+7")


def _get_alert_webhook() -> str:
    """Lấy webhook URL cho alert.

    Ưu tiên DISCORD_ALERT_WEBHOOK_URL (kênh riêng cho alert khẩn cấp).
    Fallback về DISCORD_WEBHOOK_URL nếu không có.

    Returns:
        Webhook URL string, hoặc rỗng nếu không cấu hình.
    """
    return (
        os.getenv("DISCORD_ALERT_WEBHOOK_URL", "")
        or os.getenv("DISCORD_WEBHOOK_URL", "")
    )


# ── Main service class ────────────────────────────────────────────────────────

class HealthCheckService:
    """Service giám sát trạng thái hệ thống — chạy mỗi 5 phút.

    Anti-spam state (in-memory):
        _last_failed_names: set tên checkpoint thất bại lần trước.
            Chỉ gửi alert khi set này thay đổi (lỗi mới hoặc recover).
        _last_ok_alert_at: thời điểm gửi summary OK gần nhất.
            Chỉ gửi OK summary 1 lần/giờ.
    """

    def __init__(self) -> None:
        self._last_failed_names: set[str] = set()
        self._last_ok_alert_at: Optional[datetime] = None

    async def run_once(self) -> None:
        """Thực thi 1 vòng health check cho tất cả 4 checkpoints.

        Được gọi bởi BaseScheduler mỗi 5 phút.
        Mọi exception đều được bắt và log — không để crash scheduler.
        """
        try:
            await self._execute_health_check()
        except Exception as exc:
            logger.error(
                f"[HealthCheck] LOI vong kiem tra: "
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )

    async def _execute_health_check(self) -> None:
        """Chạy 4 checkpoint song song và xử lý kết quả.

        Raises:
            Exception: Nếu có lỗi không mong đợi trong quá trình xử lý.
        """
        checked_at = _now_utc7_str()

        # Chạy 4 checkpoint song song — độc lập nhau
        results: list[CheckResult] = list(await asyncio.gather(
            _check_database(),
            _check_redis(),
            _check_bot_status(),
            _check_binance_api(),
            return_exceptions=False,
        ))

        self._log_results(results)
        await self._handle_alerting(results, checked_at)

    def _log_results(self, results: list[CheckResult]) -> None:
        """Log kết quả tất cả checkpoint ở mức INFO/WARNING.

        Args:
            results: Danh sách 4 CheckResult.
        """
        all_ok = all(r.ok for r in results)
        if all_ok:
            summary = " | ".join(f"{r.name}={r.message}" for r in results)
            logger.info(f"[HealthCheck] ALL OK — {summary}")
        else:
            for r in results:
                if r.ok:
                    logger.debug(f"[HealthCheck] {r.name}: {r.message}")
                else:
                    logger.warning(
                        f"[HealthCheck] {r.name}: FAILED — {r.detail}"
                        + (f" | {r.extra}" if r.extra else "")
                    )

    async def _handle_alerting(
        self, results: list[CheckResult], checked_at: str
    ) -> None:
        """Quyết định có gửi Discord alert không dựa trên anti-spam logic.

        Args:
            results: Danh sách 4 CheckResult.
            checked_at: Thời gian kiểm tra dạng string.
        """
        failed_names = {r.name for r in results if not r.ok}
        webhook_url  = _get_alert_webhook()

        if not webhook_url:
            logger.debug("[HealthCheck] Khong co webhook URL — bo qua Discord alert")
            return

        if failed_names:
            await self._send_failure_alert(results, failed_names, checked_at, webhook_url)
        else:
            await self._maybe_send_ok_summary(results, checked_at, webhook_url)

        self._last_failed_names = failed_names

    async def _send_failure_alert(
        self,
        results:      list[CheckResult],
        failed_names: set[str],
        checked_at:   str,
        webhook_url:  str,
    ) -> None:
        """Gửi alert khi có checkpoint thất bại — chỉ gửi khi trạng thái thay đổi.

        Args:
            results: Danh sách 4 CheckResult.
            failed_names: Set tên checkpoint thất bại lần này.
            checked_at: Thời gian kiểm tra.
            webhook_url: Discord webhook URL.
        """
        # Chỉ gửi nếu: lỗi mới xuất hiện HOẶC lỗi cũ đã recover (set thay đổi)
        if failed_names == self._last_failed_names:
            logger.debug(
                f"[HealthCheck] Trang thai loi khong doi ({failed_names}) — bo qua alert"
            )
            return

        embed = _build_alert_embed(results, checked_at)
        await send_discord_message(embed=embed, webhook_url=webhook_url)
        logger.warning(
            f"[HealthCheck] Da gui ALERT: {len(failed_names)} checkpoint that bai "
            f"({', '.join(sorted(failed_names))})"
        )

    async def _maybe_send_ok_summary(
        self,
        results:     list[CheckResult],
        checked_at:  str,
        webhook_url: str,
    ) -> None:
        """Gửi summary OK tối đa 1 lần/giờ.

        Nếu lần trước có lỗi và bây giờ OK → gửi ngay (recover notification).
        Nếu đã OK liên tục → chỉ gửi mỗi _OK_SUMMARY_INTERVAL_HOURS giờ.

        Args:
            results: Danh sách 4 CheckResult (tất cả ok=True).
            checked_at: Thời gian kiểm tra.
            webhook_url: Discord webhook URL.
        """
        now = datetime.now(timezone.utc)

        # Recover: lần trước có lỗi, bây giờ OK → gửi ngay
        if self._last_failed_names:
            embed = _build_ok_embed(results, checked_at)
            await send_discord_message(embed=embed, webhook_url=webhook_url)
            self._last_ok_alert_at = now
            logger.info("[HealthCheck] He thong da phuc hoi — da gui OK notification")
            return

        # Healthy liên tục: chỉ gửi mỗi N giờ
        if self._last_ok_alert_at is None:
            should_send = True
        else:
            elapsed = (now - self._last_ok_alert_at).total_seconds()
            should_send = elapsed >= _OK_SUMMARY_INTERVAL_HOURS * 3600

        if should_send:
            embed = _build_ok_embed(results, checked_at)
            await send_discord_message(embed=embed, webhook_url=webhook_url)
            self._last_ok_alert_at = now
            logger.info("[HealthCheck] Da gui OK summary (periodic)")


# ── Job registration ──────────────────────────────────────────────────────────

def setup_health_check_job(scheduler=None) -> None:
    """Đăng ký HealthCheckService job vào SchedulerRegistry.

    Tạo 1 instance HealthCheckService và đăng ký vào scheduler với:
    - Interval: 300 giây (5 phút)
    - Redis Lock TTL: 270 giây (< interval để tránh overlap)
    - Job ID: "health_check"

    Nên được gọi trong ``main.py`` TRƯỚC khi ``scheduler.start()``.

    Args:
        scheduler: BaseScheduler instance. Nếu None, lấy từ SchedulerRegistry.get().

    Example:
        # main.py
        from src.apps.monitoring import setup_health_check_job
        setup_health_check_job(scheduler)
        await scheduler.start()
    """
    if scheduler is None:
        scheduler = SchedulerRegistry.get()

    service = HealthCheckService()

    scheduler.add_job(
        JobConfig(
            job_id=_JOB_ID,
            func=service.run_once,
            trigger="interval",
            trigger_args={"seconds": _SCAN_INTERVAL_SECONDS},
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            max_retries=1,
            retry_delay_seconds=5.0,
            enabled=True,
        )
    )

    logger.info(
        f"[HealthCheck] Job '{_JOB_ID}' da dang ky "
        f"| interval={_SCAN_INTERVAL_SECONDS}s ({_SCAN_INTERVAL_SECONDS//60} phut) "
        f"| lock_ttl={_LOCK_TTL_SECONDS}s"
    )
