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
DISCORD_REPORT_WEBHOOK_URL = os.getenv("DISCORD_REPORT_WEBHOOK_URL", "")

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


async def send_discord_message(content: str = None, embed: dict = None, webhook_url: str = None):
    """
    Gửi message văn bản thuần hoặc embed lên Discord Webhook.

    Args:
        content: Văn bản thuần (hiển thị phía trên embed).
        embed: Dict theo cấu trúc Discord Embed object.
        webhook_url: URL webhook cụ thể. Nếu None sẽ dùng DISCORD_WEBHOOK_URL mặc định.
    """
    url = webhook_url or DISCORD_WEBHOOK_URL
    if not url:
        return

    payload = {}
    if content:
        payload["content"] = content
    if embed:
        payload["embeds"] = [embed]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 429:
                    # Rate-limited — thử lại sau 1 giây
                    data = await resp.json()
                    wait = data.get("retry_after", 1)
                    logger.warning(f"Discord rate limit, thử lại sau {wait}s")
                    await asyncio.sleep(wait)
                    async with session.post(url, json=payload) as resp2:
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


def _analyze_entry_conditions(strategy_name: str, signal: str, meta: dict, position: str) -> tuple[list, list]:
    """
    Phân tích điều kiện entry của từng chiến lược.
    Trả về (conditions_met: list[str], conditions_missing: list[str])
    """
    met = []
    missing = []

    trend = meta.get("trend")          # 1 hoặc -1
    prev_trend = meta.get("prev_trend")
    momentum = meta.get("momentum", "")
    slope_pct = meta.get("slope_pct", 0.0)
    momentum_pct = meta.get("momentum_pct", 0.0)
    was_in_pullback = meta.get("was_in_pullback")
    is_sideway = meta.get("is_sideway")

    STRONG_MOM = {"blue", "purple"}
    WEAK_MOM   = {"orange", "yellow", "green"}

    # ── Đang giữ vị thế → không cần check entry ──────────────────────────────
    if position:
        return [f"Đang giữ {position.upper()}"], []

    # ── sma_trend_early_exit ──────────────────────────────────────────────────
    if strategy_name == "sma_trend_early_exit":
        # Trend
        if trend == 1:
            met.append("✅ Trend đang TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend đang GIẢM (-1)")
        else:
            missing.append("❓ Trend chưa xác định")

        # Trend đảo chiều
        if prev_trend is not None and trend is not None and trend != prev_trend:
            met.append("✅ Trend vừa đảo chiều")
        else:
            missing.append("⏳ Chờ Trend đảo chiều")

        # Momentum
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum mạnh ({momentum})")
        else:
            missing.append(f"❌ Momentum yếu ({momentum}) — cần blue/purple")

        # Slope
        if abs(slope_pct) > 0:
            met.append(f"✅ Slope={slope_pct:+.4f}%")

    # ── sma_pullback ──────────────────────────────────────────────────────────
    elif strategy_name == "sma_pullback":
        # Trend đang chạy (không cần đảo)
        if trend == 1:
            met.append("✅ Trend đang TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend đang GIẢM (-1)")
        else:
            missing.append("❓ Trend chưa xác định")

        # Pha pullback
        if was_in_pullback is True:
            met.append("✅ Đã qua pha hồi (pullback)")
        elif was_in_pullback is False:
            missing.append("⏳ Chờ pha hồi (momentum cần orange/yellow/green)")
        else:
            missing.append("❓ Chưa có dữ liệu pullback")

        # Momentum bật lại
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum bật mạnh ({momentum})")
        elif momentum in WEAK_MOM:
            missing.append(f"⏳ Momentum đang hồi ({momentum}) — chờ bật blue/purple")
        else:
            missing.append(f"❌ Momentum ({momentum}) — cần blue/purple để trigger")

        # Slope
        if abs(slope_pct) > 0:
            met.append(f"✅ Slope={slope_pct:+.4f}%")

    # ── sma_anti_sideway ──────────────────────────────────────────────────────
    elif strategy_name == "sma_anti_sideway":
        # Bộ lọc sideway
        if is_sideway is True:
            missing.append(f"❌ Đang SIDEWAY (|Slope|={abs(slope_pct):.4f}%) — bot ngủ đông")
        elif is_sideway is False:
            met.append(f"✅ Không sideway (|Slope|={abs(slope_pct):.4f}%)")
        else:
            # Tính từ slope_pct nếu không có is_sideway
            if abs(slope_pct) >= 0.005:
                met.append(f"✅ Slope đủ mạnh ({slope_pct:+.4f}%)")
            else:
                missing.append(f"❌ Slope quá yếu ({slope_pct:+.4f}%) — thị trường sideway")

        # Trend đảo chiều
        if prev_trend is not None and trend is not None and trend != prev_trend:
            met.append("✅ Trend vừa đảo chiều")
        else:
            missing.append("⏳ Chờ Trend đảo chiều")

        # Trend hiện tại
        if trend == 1:
            met.append("✅ Trend TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend GIẢM (-1)")

        # Momentum pct
        if abs(momentum_pct) > 0:
            met.append(f"✅ MomPct={momentum_pct:+.4f}%")

    # ── Fallback cho các chiến lược khác ─────────────────────────────────────
    else:
        if trend == 1:
            met.append("✅ Trend TĂNG")
        elif trend == -1:
            met.append("✅ Trend GIẢM")
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum mạnh ({momentum})")
        else:
            missing.append(f"⏳ Momentum ({momentum})")

    return met, missing


def build_candle_status_embed(candle_time: str, bot_reports: list[dict]) -> dict:
    """
    Tạo Discord Embed báo cáo trạng thái tất cả bot sau mỗi nến đóng.
    Hiển thị rõ điều kiện đã thỏa và còn thiếu để vào lệnh.

    bot_reports: list of dict với keys:
        - bot_id, bot_name, symbol, strategy_name
        - signal: "none" | "long" | "short" | "close_long" | "close_short"
        - reason: str (lý do từ strategy)
        - position: None | "long" | "short"
        - metadata: dict (slope_pct, momentum, trend, prev_trend, ...)
    """
    fields = []
    has_signal = any(r.get("signal", "none") != "none" for r in bot_reports)

    for r in bot_reports:
        bot_id   = r.get("bot_id", "?")
        bot_name = r.get("bot_name", f"Bot#{bot_id}")
        symbol   = r.get("symbol", "?")
        signal   = r.get("signal", "none")
        position = r.get("position")
        meta     = r.get("metadata") or {}
        strategy = r.get("strategy_name", "")

        # ── Icon header ───────────────────────────────────────────────────────
        if signal == "long":
            status_icon = "🟢"
            header_suffix = "**→ VÀO LONG!**"
        elif signal == "short":
            status_icon = "🔴"
            header_suffix = "**→ VÀO SHORT!**"
        elif signal == "close_long":
            status_icon = "🔒"
            header_suffix = "**→ ĐÓNG LONG**"
        elif signal == "close_short":
            status_icon = "🔒"
            header_suffix = "**→ ĐÓNG SHORT**"
        elif position == "long":
            status_icon = "📈"
            header_suffix = "Đang giữ LONG"
        elif position == "short":
            status_icon = "📉"
            header_suffix = "Đang giữ SHORT"
        else:
            status_icon = "⏳"
            header_suffix = "Đang chờ"

        # ── Phân tích điều kiện ───────────────────────────────────────────────
        met, missing = _analyze_entry_conditions(strategy, signal, meta, position)

        # ── Build value text ──────────────────────────────────────────────────
        lines = [header_suffix]

        if met:
            lines.append("**Đã thỏa:**")
            lines.extend(f"  {c}" for c in met)

        if missing:
            lines.append("**Còn thiếu:**")
            lines.extend(f"  {c}" for c in missing)

        # Thêm slope/momentum raw nếu có
        slope = meta.get("slope_pct")
        mom   = meta.get("momentum")
        if slope is not None or mom is not None:
            raw_parts = []
            if slope is not None:
                raw_parts.append(f"Slope={slope:+.4f}%")
            if mom:
                raw_parts.append(f"Mom={mom}")
            lines.append(f"`{' | '.join(raw_parts)}`")

        value = "\n".join(lines)

        fields.append({
            "name": f"{status_icon} #{bot_id} {bot_name} — {symbol}",
            "value": value[:1024],
            "inline": False,
        })

    # Màu embed: xanh nếu có signal entry, vàng nếu có close, tối nếu chờ
    entry_signals = [r for r in bot_reports if r.get("signal") in ("long", "short")]
    close_signals = [r for r in bot_reports if r.get("signal") in ("close_long", "close_short")]
    if entry_signals:
        color = 0x00C853
    elif close_signals:
        color = 0x546E7A
    else:
        color = 0x2C2F33

    return {
        "title": f"📊 Báo cáo nến 5m — {candle_time}",
        "color": color,
        "fields": fields[:25],
        "footer": {"text": "Trading Bot — ittuantruong"},
        "timestamp": _utc_now_iso(),
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
