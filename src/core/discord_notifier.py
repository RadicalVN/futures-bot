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
            for attempt in range(3):  # Thử tối đa 3 lần
                try:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 429:
                            data = await resp.json()
                            wait = data.get("retry_after", 2)
                            logger.warning(f"Discord rate limit, thử lại sau {wait}s")
                            await asyncio.sleep(wait)
                            continue
                        elif resp.status in (500, 502, 503, 504):
                            wait = 2 ** attempt  # 1s, 2s, 4s
                            logger.warning(f"Discord server error {resp.status}, thử lại sau {wait}s (lần {attempt+1}/3)")
                            await asyncio.sleep(wait)
                            continue
                        elif resp.status not in (200, 204):
                            text = await resp.text()
                            logger.warning(f"Lỗi gửi Discord: {resp.status} — {text}")
                        break  # Thành công hoặc lỗi không retry được
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    wait = 2 ** attempt
                    logger.warning(f"Discord kết nối lỗi (lần {attempt+1}/3): {e}, thử lại sau {wait}s")
                    if attempt < 2:
                        await asyncio.sleep(wait)
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


def _analyze_entry_conditions(strategy_name: str, signal: str, meta: dict, position: str,
                               params: dict = None) -> tuple[list, list]:
    """
    Phân tích điều kiện entry của từng chiến lược.
    Trả về (conditions_met: list[str], conditions_missing: list[str])
    Trả về ([], []) nếu chưa có dữ liệu phân tích.
    """
    met = []
    missing = []
    p = params or {}

    # ── Đang giữ vị thế → không cần check entry ──────────────────────────────
    if position:
        return [f"Đang giữ {position.upper()}"], []

    # ── Chưa có dữ liệu → không phân tích ────────────────────────────────────
    if not meta:
        return [], []

    trend        = meta.get("trend")
    prev_trend   = meta.get("prev_trend")
    momentum     = meta.get("momentum", "")
    slope_pct    = meta.get("slope_pct", 0.0)
    momentum_pct = meta.get("momentum_pct", 0.0)
    was_in_pullback = meta.get("was_in_pullback")
    is_sideway   = meta.get("is_sideway")

    STRONG_MOM = {"blue", "purple"}
    WEAK_MOM   = {"orange", "yellow", "green"}

    # ── sma_trend_early_exit ──────────────────────────────────────────────────
    if strategy_name == "sma_trend_early_exit":
        min_slope = p.get("min_slope_pct", 0.0)

        # Trend hiện tại
        if trend == 1:
            met.append("✅ Trend TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend GIẢM (-1)")
        else:
            missing.append("❓ Trend chưa xác định")

        # Trend đảo chiều — chỉ hiện khi biết prev_trend
        if prev_trend is not None and trend is not None:
            if trend != prev_trend:
                met.append("✅ Trend vừa đảo chiều")
            else:
                missing.append(f"⏳ Chờ Trend đảo chiều (hiện: {trend:+.0f} → {trend:+.0f})")

        # Momentum
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum mạnh ({momentum})")
        elif momentum:
            missing.append(f"❌ Momentum={momentum} — cần blue/purple")

        # Slope (chỉ check nếu có ngưỡng)
        if min_slope > 0:
            if abs(slope_pct) >= min_slope:
                met.append(f"✅ |Slope|={abs(slope_pct):.4f}% ≥ {min_slope:.4f}%")
            else:
                missing.append(f"❌ |Slope|={abs(slope_pct):.4f}% < ngưỡng {min_slope:.4f}%")

    # ── sma_pullback ──────────────────────────────────────────────────────────
    elif strategy_name == "sma_pullback":
        min_slope    = p.get("min_slope_pct", 0.0)
        confirm_bars = p.get("pullback_confirm_bars", 2)

        # Trend
        if trend == 1:
            met.append("✅ Trend TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend GIẢM (-1)")
        else:
            missing.append("❓ Trend chưa xác định")

        # Pha pullback
        if was_in_pullback is True:
            met.append(f"✅ Đã qua pha hồi ({confirm_bars} nến)")
        elif was_in_pullback is False:
            missing.append(f"⏳ Chờ pha hồi {confirm_bars} nến (Mom cần orange/yellow/green)")

        # Momentum bật lại
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum bật mạnh ({momentum})")
        elif momentum in WEAK_MOM:
            missing.append(f"⏳ Momentum={momentum} đang hồi — chờ bật blue/purple")
        elif momentum:
            missing.append(f"❌ Momentum={momentum} — cần blue/purple để trigger")

        # Slope
        if min_slope > 0:
            if abs(slope_pct) >= min_slope:
                met.append(f"✅ |Slope|={abs(slope_pct):.4f}% ≥ {min_slope:.4f}%")
            else:
                missing.append(f"❌ |Slope|={abs(slope_pct):.4f}% < ngưỡng {min_slope:.4f}%")

    # ── sma_anti_sideway ──────────────────────────────────────────────────────
    elif strategy_name == "sma_anti_sideway":
        sideway_thr = p.get("sideway_slope_threshold", 0.01)
        min_mom_pct = p.get("min_momentum_pct", 0.0)

        # Bộ lọc sideway
        if is_sideway is True:
            missing.append(f"❌ SIDEWAY: |Slope|={abs(slope_pct):.4f}% < {sideway_thr:.4f}%")
        elif is_sideway is False:
            met.append(f"✅ Không sideway: |Slope|={abs(slope_pct):.4f}% ≥ {sideway_thr:.4f}%")
        else:
            # Tính từ slope_pct nếu không có is_sideway
            if abs(slope_pct) >= sideway_thr:
                met.append(f"✅ |Slope|={abs(slope_pct):.4f}% ≥ {sideway_thr:.4f}%")
            else:
                missing.append(f"❌ |Slope|={abs(slope_pct):.4f}% < ngưỡng {sideway_thr:.4f}%")

        # Trend hiện tại
        if trend == 1:
            met.append("✅ Trend TĂNG (1)")
        elif trend == -1:
            met.append("✅ Trend GIẢM (-1)")

        # Trend đảo chiều
        if prev_trend is not None and trend is not None:
            if trend != prev_trend:
                met.append("✅ Trend vừa đảo chiều")
            else:
                missing.append(f"⏳ Chờ Trend đảo chiều")

        # Momentum pct
        if min_mom_pct > 0:
            if abs(momentum_pct) >= min_mom_pct:
                met.append(f"✅ |MomPct|={abs(momentum_pct):.4f}% ≥ {min_mom_pct:.4f}%")
            else:
                missing.append(f"❌ |MomPct|={abs(momentum_pct):.4f}% < ngưỡng {min_mom_pct:.4f}%")

    # ── sma_macd_cross ────────────────────────────────────────────────────────
    elif strategy_name == "sma_macd_cross":
        ma_color   = meta.get("ma_color", "")
        sig_color  = meta.get("sig_color", "")
        macd_color = meta.get("macd_color", "")
        close_val  = meta.get("close", 0)
        ma_val     = meta.get("ma", 0)

        BULLISH = {"blue", "green"}
        BEARISH = {"red", "orange"}

        if signal_type == "long" or (not signal_type and trend == 1):
            # Điều kiện 1: Signal chuyển từ bearish → bullish/reversal
            if sig_color in BULLISH | {"purple"}:
                met.append(f"✅ MACD-Signal chuyển {sig_color} (từ bearish)")
            elif sig_color in BEARISH:
                missing.append(f"❌ MACD-Signal={sig_color} — cần chuyển sang tím/xanh")

            # Điều kiện 2: MACD golden cross
            macd_v = meta.get("macd", 0)
            sig_v  = meta.get("macd_signal", 0)
            if macd_v > sig_v:
                met.append(f"✅ MACD > Signal (golden cross)")
            else:
                missing.append(f"⏳ Chờ MACD cắt lên Signal")

            # Điều kiện 3: Giá trên MA
            if close_val and ma_val:
                if close_val > ma_val:
                    met.append(f"✅ Giá ({close_val:.4f}) trên MA ({ma_val:.4f})")
                else:
                    missing.append(f"⏳ Giá ({close_val:.4f}) chưa cắt lên MA ({ma_val:.4f})")

            if ma_color:
                met.append(f"✅ MA={ma_color}") if ma_color in BULLISH else missing.append(f"⏳ MA={ma_color}")

        else:  # short
            if sig_color in BEARISH | {"purple"}:
                met.append(f"✅ MACD-Signal chuyển {sig_color} (từ bullish)")
            elif sig_color in BULLISH:
                missing.append(f"❌ MACD-Signal={sig_color} — cần chuyển sang tím/đỏ/cam")

            macd_v = meta.get("macd", 0)
            sig_v  = meta.get("macd_signal", 0)
            if macd_v < sig_v:
                met.append(f"✅ MACD < Signal (death cross)")
            else:
                missing.append(f"⏳ Chờ MACD cắt xuống Signal")

            if close_val and ma_val:
                if close_val < ma_val:
                    met.append(f"✅ Giá ({close_val:.4f}) dưới MA ({ma_val:.4f})")
                else:
                    missing.append(f"⏳ Giá ({close_val:.4f}) chưa cắt xuống MA ({ma_val:.4f})")

            if ma_color:
                met.append(f"✅ MA={ma_color}") if ma_color in BEARISH else missing.append(f"⏳ MA={ma_color}")

    # ── Fallback ──────────────────────────────────────────────────────────────
    else:
        if trend == 1:
            met.append("✅ Trend TĂNG")
        elif trend == -1:
            met.append("✅ Trend GIẢM")
        if momentum in STRONG_MOM:
            met.append(f"✅ Momentum mạnh ({momentum})")
        elif momentum:
            missing.append(f"⏳ Momentum={momentum} — cần blue/purple")

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
        params   = r.get("strategy_params") or {}
        no_data  = r.get("no_data", False)

        # ── Icon header ───────────────────────────────────────────────────────
        if no_data and not position:
            status_icon = "⚠️"
            header_suffix = f"Thiếu dữ liệu"
        elif signal == "long":
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
        met, missing = _analyze_entry_conditions(strategy, signal, meta, position, params)

        # ── Build value text ──────────────────────────────────────────────────
        lines = [header_suffix]

        if no_data and not position:
            error_msg = meta.get("error", r.get("reason", "Không rõ"))
            tb = meta.get("traceback", "")
            if tb:
                lines.append(f"**Lỗi:** `{error_msg[:200]}`")
                tb_lines = [l for l in tb.strip().splitlines() if l.strip()]
                tb_short = "\n".join(tb_lines[-4:]) if len(tb_lines) > 4 else "\n".join(tb_lines)
                lines.append(f"```\n{tb_short[:500]}\n```")
            else:
                lines.append(f"```{error_msg[:300]}```")

        elif not meta and not position:
            lines.append("_Chưa có dữ liệu — chờ chu kỳ quét đầu tiên_")

        else:
            ready_to_enter = met and not missing and not position

            if ready_to_enter:
                # ── ĐỦ ĐIỀU KIỆN: hiển thị đầy đủ thông tin để vào lệnh ──────
                side_label = "SHORT 🔴" if "GIẢM" in " ".join(met) or meta.get("trend") == -1 else "LONG 🟢"
                entry_price = meta.get("entry_price") or meta.get("price", 0)
                sl = meta.get("stop_loss") or params.get("stop_loss_pct", 0.02)
                tp = meta.get("take_profit") or params.get("take_profit_pct", 0.04)
                leverage = params.get("leverage", 5)
                reason_text = r.get("reason", "")

                lines.append(f"**🚀 ĐỦ ĐIỀU KIỆN VÀO LỆNH — {side_label}**")
                lines.append("")
                lines.append("**Điều kiện đã thỏa:**")
                lines.extend(f"  {c}" for c in met)
                lines.append("")

                # Thông tin giao dịch
                info_parts = []
                if entry_price:
                    info_parts.append(f"💰 Giá: `{entry_price:,.4f}`")
                info_parts.append(f"⚙️ Đòn bẩy: `{leverage}x`")
                if isinstance(sl, float) and sl < 1:
                    info_parts.append(f"🛑 SL: `{sl*100:.1f}%`")
                if isinstance(tp, float) and tp < 1:
                    info_parts.append(f"🎯 TP: `{tp*100:.1f}%`")
                if info_parts:
                    lines.append("  ".join(info_parts))

                if reason_text:
                    lines.append(f"📝 `{reason_text[:200]}`")

                # Raw indicators
                slope = meta.get("slope_pct")
                mom   = meta.get("momentum")
                if slope is not None or mom is not None:
                    raw_parts = []
                    if slope is not None:
                        raw_parts.append(f"Slope={slope:+.4f}%")
                    if mom:
                        raw_parts.append(f"Mom={mom}")
                    lines.append(f"`{' | '.join(raw_parts)}`")

            else:
                # ── Chưa đủ điều kiện: hiển thị đã thỏa / còn thiếu ──────────
                if met:
                    lines.append("**Đã thỏa:**")
                    lines.extend(f"  {c}" for c in met)

                if missing:
                    lines.append("**Còn thiếu:**")
                    lines.extend(f"  {c}" for c in missing)

                # Raw indicators
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

    # Màu embed: xanh nếu có signal entry, vàng nếu có close, cam nếu có lỗi data, tối nếu chờ
    entry_signals = [r for r in bot_reports if r.get("signal") in ("long", "short")]
    close_signals = [r for r in bot_reports if r.get("signal") in ("close_long", "close_short")]
    data_errors   = [r for r in bot_reports if r.get("no_data") and not r.get("position")]
    if entry_signals:
        color = 0x00C853
    elif close_signals:
        color = 0x546E7A
    elif data_errors:
        color = 0xFF6D00  # Cam cảnh báo
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
