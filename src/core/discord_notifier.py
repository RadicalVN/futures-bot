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


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
