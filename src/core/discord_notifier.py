"""
discord_notifier.py — Gửi thông báo qua Discord Webhooks

Cấu hình trong .env:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN

Hỗ trợ:
- Embed message màu sắc theo loại tín hiệu (LONG=xanh, SHORT=đỏ, CLOSE=xám)
- Hiển thị đầy đủ thông tin: Symbol, Giá, SL/TP, Lý do, PnL
- Retry 1 lần nếu Discord trả về lỗi 429 (rate limit)
"""
import os
import asyncio
import aiohttp
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Màu embed theo loại lệnh (decimal color code)
COLORS = {
    "long":        0x00C853,  # Xanh lá
    "short":       0xF6465D,  # Đỏ
    "close_long":  0x546E7A,  # Xám xanh
    "close_short": 0x546E7A,  # Xám xanh
    "error":       0xFF6D00,  # Cam cảnh báo
    "info":        0x2196F3,  # Xanh dương
}

SIGNAL_LABELS = {
    "long":        "🟢 MỞ LONG",
    "short":       "🔴 MỞ SHORT",
    "close_long":  "🔒 ĐÓNG LONG",
    "close_short": "🔒 ĐÓNG SHORT",
}


async def send_discord_message(content: str = None, embed: dict = None):
    """
    Gửi message văn bản thuần hoặc embed lên Discord Webhook.

    Args:
        content: Văn bản thuần (hiển thị phía trên embed).
        embed: Dict theo cấu trúc Discord Embed object.
    """
    if not DISCORD_WEBHOOK_URL:
        return

    payload = {}
    if content:
        payload["content"] = content
    if embed:
        payload["embeds"] = [embed]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                if resp.status == 429:
                    # Rate-limited — thử lại sau 1 giây
                    data = await resp.json()
                    wait = data.get("retry_after", 1)
                    logger.warning(f"Discord rate limit, thử lại sau {wait}s")
                    await asyncio.sleep(wait)
                    async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp2:
                        if resp2.status not in (200, 204):
                            logger.warning(f"Discord retry thất bại: {resp2.status}")
                elif resp.status not in (200, 204):
                    text = await resp.text()
                    logger.warning(f"Lỗi gửi Discord: {resp.status} — {text}")
    except Exception as e:
        logger.error(f"Lỗi kết nối Discord Webhook: {e}")


def build_entry_embed(bot_id, signal_type: str, symbol: str,
                      entry_price: float, amount: float, leverage: int,
                      stop_loss: float, take_profit: float, reason: str) -> dict:
    """Tạo Discord Embed cho lệnh MỞ (LONG/SHORT)."""
    label = SIGNAL_LABELS.get(signal_type, signal_type.upper())
    color = COLORS.get(signal_type, 0x607D8B)

    return {
        "title": f"{label} #{bot_id} — {symbol}",
        "color": color,
        "fields": [
            {"name": "💰 Giá vào",       "value": f"`{entry_price:,.4f}`",  "inline": True},
            {"name": "📦 Khối lượng",    "value": f"`{amount}`",            "inline": True},
            {"name": "⚙️ Đòn bẩy",       "value": f"`{leverage}x`",         "inline": True},
            {"name": "🛑 Stop Loss",     "value": f"`{stop_loss:,.4f}`",    "inline": True},
            {"name": "🎯 Take Profit",   "value": f"`{take_profit:,.4f}`",  "inline": True},
            {"name": "📝 Lý do",         "value": reason[:1024],             "inline": False},
        ],
        "footer": {"text": "Trading Bot — ittuantruong"},
        "timestamp": _utc_now_iso(),
    }


def build_exit_embed(bot_id, signal_type: str, symbol: str,
                     close_price, pnl, reason: str) -> dict:
    """Tạo Discord Embed cho lệnh ĐÓNG vị thế."""
    label = SIGNAL_LABELS.get(signal_type, "🔒 ĐÓNG")
    color = COLORS.get(signal_type, 0x607D8B)

    try:
        pnl_float = float(pnl)
        pnl_str = f"`{pnl_float:+.4f} USDT`"
        # Đổi màu embed theo lãi/lỗ
        color = 0x00C853 if pnl_float > 0 else (0xF6465D if pnl_float < 0 else color)
    except (TypeError, ValueError):
        pnl_str = f"`{pnl}`"

    return {
        "title": f"{label} #{bot_id} — {symbol}",
        "color": color,
        "fields": [
            {"name": "💸 Giá đóng",  "value": f"`{close_price}`", "inline": True},
            {"name": "💵 PnL",       "value": pnl_str,             "inline": True},
            {"name": "📝 Lý do",     "value": reason[:1024],       "inline": False},
        ],
        "footer": {"text": "Trading Bot — ittuantruong"},
        "timestamp": _utc_now_iso(),
    }


def build_error_embed(bot_id, symbol: str, error: str) -> dict:
    """Tạo Discord Embed cho lỗi đặt lệnh."""
    return {
        "title": f"⚠️ Lỗi đặt lệnh #{bot_id} — {symbol}",
        "color": COLORS["error"],
        "fields": [
            {"name": "❌ Chi tiết lỗi", "value": f"```{error[:1000]}```", "inline": False},
        ],
        "footer": {"text": "Trading Bot — ittuantruong"},
        "timestamp": _utc_now_iso(),
    }


def build_candle_status_embed(candle_time: str, bot_reports: list[dict]) -> dict:
    """
    Tạo Discord Embed báo cáo trạng thái tất cả bot sau mỗi nến đóng.

    bot_reports: list of dict với keys:
        - bot_id, bot_name, symbol, strategy_name
        - signal: "none" | "long" | "short" | "close_long" | "close_short"
        - reason: str (lý do từ strategy)
        - position: None | "long" | "short"  (vị thế đang giữ)
        - metadata: dict (slope_pct, momentum, ...)
    """
    fields = []
    has_signal = any(r.get("signal", "none") != "none" for r in bot_reports)

    for r in bot_reports:
        bot_id     = r.get("bot_id", "?")
        bot_name   = r.get("bot_name", f"Bot#{bot_id}")
        symbol     = r.get("symbol", "?")
        signal     = r.get("signal", "none")
        reason     = r.get("reason", "—")
        position   = r.get("position")
        meta       = r.get("metadata") or {}

        # Icon trạng thái
        if signal == "long":
            status_icon = "🟢"
        elif signal == "short":
            status_icon = "🔴"
        elif signal in ("close_long", "close_short"):
            status_icon = "🔒"
        elif position == "long":
            status_icon = "📈"
        elif position == "short":
            status_icon = "📉"
        else:
            status_icon = "⏳"

        # Dòng metadata ngắn gọn
        meta_parts = []
        if "slope_pct" in meta:
            meta_parts.append(f"Slope={meta['slope_pct']:+.4f}%")
        if "momentum" in meta:
            meta_parts.append(f"Mom={meta['momentum']}")
        if "momentum_pct" in meta:
            meta_parts.append(f"MomPct={meta['momentum_pct']:+.4f}%")
        if "was_in_pullback" in meta:
            meta_parts.append(f"Pullback={'✅' if meta['was_in_pullback'] else '❌'}")
        if "is_sideway" in meta:
            meta_parts.append(f"Sideway={'✅' if meta['is_sideway'] else '❌'}")
        meta_str = " | ".join(meta_parts) if meta_parts else ""

        pos_str = f"Đang giữ: **{position.upper()}**" if position else "Không có vị thế"
        value = f"{pos_str}\n{reason[:200]}"
        if meta_str:
            value += f"\n`{meta_str}`"

        fields.append({
            "name": f"{status_icon} #{bot_id} {bot_name} — {symbol}",
            "value": value[:1024],
            "inline": False,
        })

    color = 0x00C853 if has_signal else 0x2C2F33  # Xanh nếu có signal, tối nếu chờ

    return {
        "title": f"📊 Báo cáo nến 5m — {candle_time}",
        "color": color,
        "fields": fields[:25],  # Discord giới hạn 25 fields
        "footer": {"text": "Trading Bot — ittuantruong"},
        "timestamp": _utc_now_iso(),
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
