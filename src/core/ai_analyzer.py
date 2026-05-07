"""
ai_analyzer.py — AI Strategy Analyzer sử dụng Google Gemini.

Cung cấp một lớp "second opinion" cho các tín hiệu giao dịch:
Strategy tìm thấy entry → AI phân tích OHLCV + indicators → approve/reject.

Thiết kế:
    - Fail-open: Nếu Gemini API lỗi/timeout → decision="skip" → đặt lệnh bình thường.
      AI là lớp bổ sung, không phải điểm chặn cứng.
    - Rate limit protection: asyncio.Semaphore toàn cục giới hạn số request
      đồng thời, kết hợp exponential backoff khi gặp 429.
    - Per-bot opt-in: ai_filter_enabled=False (default) → bỏ qua hoàn toàn.
    - Kết quả lưu vào metadata của EntryOpportunity/Trade để thống kê win-rate.
    - Few-shot learning: tự động fetch Top 3 dislike examples theo strategy_name
      từ DB và đưa vào System Prompt để AI học từ lỗi quá khứ.

Cấu hình qua Bot.parameters:
    ai_filter_enabled:  bool  — Bật/tắt AI filter (default: False)
    ai_min_confidence:  int   — Reject nếu confidence < N dù decision=approve (default: 60)
    ai_timeout_seconds: float — Timeout cho Gemini API call (default: 10.0)

Biến môi trường:
    GEMINI_API_KEY: API key từ https://aistudio.google.com/app/apikey
"""
import asyncio
import json
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

# ── Hằng số ───────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_SECONDS: float = 10.0
"""Timeout mặc định cho mỗi Gemini API call."""

_DEFAULT_MIN_CONFIDENCE: int = 60
"""Ngưỡng confidence tối thiểu để approve (dù Gemini trả về approve)."""

_MAX_CONCURRENT_AI_CALLS: int = 3
"""Số lượng Gemini API call đồng thời tối đa — tránh rate limit Free tier."""

_RATE_LIMIT_RETRY_DELAYS: list[float] = [2.0, 5.0, 10.0]
"""Thời gian chờ (giây) trước mỗi lần retry khi gặp rate limit 429."""

_OHLCV_CANDLES_FOR_PROMPT: int = 10
"""Số nến gần nhất đưa vào prompt (đủ để AI đọc cấu trúc, không quá dài)."""

_GEMINI_MODEL: str = "gemini-1.5-flash"
"""Model Gemini sử dụng. Flash = nhanh + rẻ, phù hợp cho real-time trading."""

# Semaphore toàn cục — chia sẻ giữa tất cả BotEngine instances trong cùng process.
# Giới hạn số request đồng thời để tránh rate limit Free tier (15 RPM).
_global_ai_semaphore: asyncio.Semaphore = asyncio.Semaphore(_MAX_CONCURRENT_AI_CALLS)

# ── Few-shot constants ────────────────────────────────────────────────────────

_FEW_SHOT_LIMIT: int = 3
"""Số lượng dislike examples tối đa đưa vào prompt.
3 examples ≈ 200 tokens — an toàn với Gemini Flash 1M token limit."""

_FEW_SHOT_SNIPPET_MAX_CHARS: int = 200
"""Giới hạn độ dài mỗi snippet (chars) để kiểm soát token budget."""

_FEW_SHOT_COMMENT_MAX_CHARS: int = 100
"""Giới hạn độ dài user comment trong snippet."""


# ── Few-shot DB helper ────────────────────────────────────────────────────────

async def _fetch_dislike_examples(strategy_name: str) -> list[dict]:
    """Fetch Top N dislike examples từ DB theo strategy_name.

    Query AIFeedback JOIN Trade để lấy đủ context:
    - AI decision + confidence tại thời điểm sai
    - realized_pnl thực tế (kết quả tài chính)
    - User comment (lý do người dùng đánh giá AI sai)

    Fail-open: Mọi lỗi DB đều trả về [] — không crash analyzer.
    Không import từ apps.* để tuân thủ No Cross-App Imports rule.

    Args:
        strategy_name: Tên chiến lược để lọc examples đúng context.

    Returns:
        List dict chứa context của từng dislike example.
        Trả về [] nếu DB rỗng hoặc gặp lỗi.
    """
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from src.database.db import AsyncSessionLocal
        from src.database.models import AIFeedback, Trade

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AIFeedback)
                .options(selectinload(AIFeedback.trade))
                .where(
                    AIFeedback.rating == "dislike",
                    AIFeedback.trade_id.isnot(None),
                )
                .order_by(AIFeedback.created_at.desc())
                .limit(_FEW_SHOT_LIMIT * 3)  # Lấy dư để lọc theo strategy
            )
            feedbacks = result.scalars().all()

        # Lọc theo strategy_name và lấy đủ thông tin
        examples = []
        for fb in feedbacks:
            trade = fb.trade
            if not trade:
                continue
            # Lọc đúng strategy — cá nhân hóa bài học
            if trade.strategy and trade.strategy != strategy_name:
                continue

            meta = trade.signal_metadata or {}
            examples.append({
                "symbol":        trade.symbol or "UNKNOWN",
                "signal_type":   (trade.signal_type or "unknown").upper(),
                "strategy":      trade.strategy or strategy_name,
                "ai_decision":   fb.ai_decision or "approve",
                "ai_confidence": fb.ai_confidence or 0,
                "ai_analysis":   (meta.get("ai_analysis") or "")[:_FEW_SHOT_COMMENT_MAX_CHARS],
                "realized_pnl":  trade.realized_pnl,
                "user_comment":  (fb.comment or "")[:_FEW_SHOT_COMMENT_MAX_CHARS],
            })
            if len(examples) >= _FEW_SHOT_LIMIT:
                break

        return examples

    except Exception as exc:
        logger.debug(
            f"[AIAnalyzer] _fetch_dislike_examples loi (bo qua, dung prompt mac dinh): "
            f"{type(exc).__name__}: {exc}"
        )
        return []


def _build_few_shot_section(examples: list[dict]) -> str:
    """Chuyển danh sách dislike examples thành phần # MISTAKES TO AVOID.

    Mỗi snippet được bọc trong tag <past_mistake> để Gemini phân biệt
    rõ đây là dữ liệu tham khảo quá khứ, không phải lệnh hiện tại.

    Format mỗi snippet:
        <past_mistake>
        [N] Signal: LONG BTCUSDT | Strategy: sma_macd_cross
            AI Decision: APPROVE (Conf: 72) → Actual: LOSS (-8.50 USDT)
            User Feedback: "AI bỏ qua divergence MACD khi sideway"
        </past_mistake>

    Args:
        examples: List dict từ _fetch_dislike_examples().

    Returns:
        String phần few-shot, hoặc "" nếu examples rỗng.
    """
    if not examples:
        return ""

    lines = [
        "",
        "# MISTAKES TO AVOID (Lessons from Historical Errors)",
        "# The following are PAST MISTAKES you made. Learn from them.",
        "<historical_context>",
    ]

    for i, ex in enumerate(examples, start=1):
        pnl = ex.get("realized_pnl")
        if pnl is not None:
            result_label = f"WIN (+{pnl:.2f} USDT)" if pnl > 0 else f"LOSS ({pnl:.2f} USDT)"
        else:
            result_label = "LOSS (unknown amount)"

        comment = ex.get("user_comment", "").strip()
        comment_line = f'\n    User Feedback: "{comment}"' if comment else ""

        snippet = (
            f"<past_mistake>\n"
            f"[{i}] Signal: {ex['signal_type']} {ex['symbol']} "
            f"| Strategy: {ex['strategy']}\n"
            f"    AI Decision: {ex['ai_decision'].upper()} "
            f"(Conf: {ex['ai_confidence']}) → Actual: {result_label}"
            f"{comment_line}\n"
            f"</past_mistake>"
        )
        lines.append(snippet)

    lines.extend([
        "</historical_context>",
        "# Apply these lessons: be more cautious in similar situations.",
        "# Do NOT repeat these mistakes in your current analysis.",
        "",
    ])

    return "\n".join(lines)

# ── System Prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str = """You are a Professional Price Action Trader with 15+ years of experience \
in crypto futures markets (BTC, ETH, altcoins). You specialize in reading \
candle structure, momentum shifts, and trend confirmation.

Your role is to provide a SECOND OPINION on trade signals generated by \
algorithmic strategies. You are the final gatekeeper before a real order \
is placed with real money.

You analyze:
1. Recent candle structure: body size vs wicks, engulfing patterns, \
   momentum candles, exhaustion signals
2. Technical indicators: MACD histogram direction, SMA slope, momentum color
3. Market context: trend strength, sideway detection, divergence

Decision criteria:
- APPROVE: Price action CONFIRMS the signal. Momentum is aligned. \
  No obvious reversal pattern. Risk/reward is acceptable.
- REJECT: You see divergence, weak/exhausted momentum, dangerous wick \
  structure, or the signal appears to be a false breakout.

Response format — you MUST respond with ONLY a valid JSON object, \
no markdown, no explanation outside the JSON:
{
  "decision": "approve" or "reject",
  "confidence_score": integer 0-100,
  "analysis": "1-2 sentence explanation of your reasoning"
}

Rules:
- confidence_score > 70: strong conviction
- confidence_score 50-70: moderate, proceed with caution
- confidence_score < 50: weak signal, lean toward reject
- analysis must be concise and actionable (max 80 words)
- NEVER include anything outside the JSON object
- If data is insufficient, reject with confidence_score=30"""

# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class AIAnalysisResult:
    """Kết quả phân tích từ AI Analyzer.

    Attributes:
        decision: "approve" | "reject" | "skip".
            "skip" = AI không khả dụng (lỗi/timeout) → fail-open, đặt lệnh bình thường.
        confidence_score: Mức độ tự tin 0-100. 0 khi decision="skip".
        analysis: Giải thích ngắn gọn từ AI. Rỗng khi decision="skip".
        raw_response: Raw JSON string từ Gemini (để debug). Rỗng khi skip.
        latency_ms: Thời gian gọi API (ms). 0 khi skip.
        skipped_reason: Lý do skip nếu decision="skip".
    """
    decision:        str
    confidence_score: int
    analysis:        str
    raw_response:    str   = ""
    latency_ms:      float = 0.0
    skipped_reason:  str   = ""

    def to_metadata_dict(self) -> dict:
        """Chuyển sang dict để lưu vào EntryOpportunity.metadata hoặc Trade.signal_metadata.

        Returns:
            Dict JSON-serializable chứa toàn bộ thông tin AI decision.
        """
        return {
            "ai_decision":          self.decision,
            "ai_confidence_score":  self.confidence_score,
            "ai_analysis":          self.analysis,
            "ai_latency_ms":        round(self.latency_ms, 1),
            "ai_skipped_reason":    self.skipped_reason,
        }


# ── Prompt builder ────────────────────────────────────────────────────────────

def _format_ohlcv_table(ohlcv: list) -> str:
    """Format N nến gần nhất thành bảng text cho prompt.

    Chỉ lấy _OHLCV_CANDLES_FOR_PROMPT nến cuối để giữ prompt ngắn gọn.

    Args:
        ohlcv: List [[timestamp_ms, open, high, low, close, volume], ...].

    Returns:
        String bảng dạng text, mỗi dòng là 1 nến.
    """
    recent = ohlcv[-_OHLCV_CANDLES_FOR_PROMPT:]
    lines = ["  #  |    Open    |    High    |    Low     |   Close    |   Volume"]
    lines.append("-----|------------|------------|------------|------------|----------")
    for i, c in enumerate(recent, start=1):
        ts_ms, o, h, l, close, vol = c[0], c[1], c[2], c[3], c[4], c[5]
        lines.append(
            f"  {i:2d} | {o:10.4f} | {h:10.4f} | {l:10.4f} | {close:10.4f} | {vol:10.2f}"
        )
    return "\n".join(lines)


def _build_user_prompt(
    signal_type:   str,
    symbol:        str,
    strategy_name: str,
    signal_reason: str,
    ohlcv:         list,
    current_price: float,
    timeframe:     str,
    metadata:      dict,
    indicator_data: dict,
) -> str:
    """Xây dựng user prompt đầy đủ cho Gemini.

    Args:
        signal_type: "long" hoặc "short".
        symbol: Symbol giao dịch (vd: "BTC/USDT").
        strategy_name: Tên chiến lược.
        signal_reason: Lý do signal từ strategy.
        ohlcv: Dữ liệu nến OHLCV.
        current_price: Giá hiện tại.
        timeframe: Timeframe (vd: "5m").
        metadata: Metadata từ strategy (trend, momentum, slope, ...).
        indicator_data: Dict chứa ma_fast, ma_slow, macd, macd_signal, ...

    Returns:
        User prompt string đầy đủ.
    """
    direction = "LONG (BUY)" if signal_type == "long" else "SHORT (SELL)"
    ohlcv_table = _format_ohlcv_table(ohlcv)

    # Trích xuất indicators từ metadata và indicator_data
    trend        = metadata.get("trend", "N/A")
    prev_trend   = metadata.get("prev_trend", "N/A")
    momentum     = metadata.get("momentum", "N/A")
    slope_pct    = metadata.get("slope_pct", 0.0)
    is_sideway   = metadata.get("is_sideway", False)
    ma_color     = metadata.get("ma_color", "N/A")
    sig_color    = metadata.get("sig_color", "N/A")
    macd_color   = metadata.get("macd_color", "N/A")

    ma_fast      = indicator_data.get("ma_fast", "N/A")
    ma_slow      = indicator_data.get("ma_slow", "N/A")
    macd_val     = indicator_data.get("macd", "N/A")
    macd_sig     = indicator_data.get("macd_signal", "N/A")
    macd_hist    = indicator_data.get("macd_histogram", "N/A")

    # Format số nếu là float
    def _fmt(v, decimals: int = 4) -> str:
        if isinstance(v, float):
            return f"{v:.{decimals}f}"
        return str(v)

    lines = [
        f"=== TRADE SIGNAL ANALYSIS REQUEST ===",
        f"",
        f"Signal:    {direction} {symbol}",
        f"Strategy:  {strategy_name}",
        f"Timeframe: {timeframe}",
        f"Price:     {_fmt(current_price)}",
        f"Reason:    {signal_reason}",
        f"",
        f"--- Recent {_OHLCV_CANDLES_FOR_PROMPT} Candles (OHLCV) ---",
        ohlcv_table,
        f"",
        f"--- Technical Indicators ---",
        f"SMA Trend:    {trend} (prev: {prev_trend})",
        f"Momentum:     {momentum} | Slope: {_fmt(slope_pct, 4)}%",
        f"Sideway:      {'YES - caution' if is_sideway else 'NO'}",
        f"MA Color:     {ma_color} | Signal Color: {sig_color} | MACD Color: {macd_color}",
        f"MA Fast:      {_fmt(ma_fast)} | MA Slow: {_fmt(ma_slow)}",
        f"MACD:         {_fmt(macd_val, 6)} | Signal: {_fmt(macd_sig, 6)} | Hist: {_fmt(macd_hist, 6)}",
        f"",
        f"Should I enter this {direction} trade? Respond in JSON only.",
    ]
    return "\n".join(lines)


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_gemini_response(raw_text: str) -> tuple[str, int, str]:
    """Parse JSON response từ Gemini, xử lý các trường hợp format không chuẩn.

    Gemini đôi khi bọc JSON trong markdown code block (```json ... ```).
    Hàm này strip markdown và parse JSON thuần.

    Args:
        raw_text: Raw text response từ Gemini.

    Returns:
        Tuple (decision, confidence_score, analysis).

    Raises:
        ValueError: Nếu không parse được JSON hoặc thiếu field bắt buộc.
    """
    # Strip markdown code block nếu có
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Tìm JSON object đầu tiên trong text (phòng trường hợp có text thừa)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Khong tim thay JSON object trong response: {text[:200]!r}")

    data = json.loads(match.group())

    decision = str(data.get("decision", "")).lower().strip()
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision phai la 'approve' hoac 'reject', got: {decision!r}")

    confidence_score = int(data.get("confidence_score", 0))
    confidence_score = max(0, min(100, confidence_score))  # clamp [0, 100]

    analysis = str(data.get("analysis", "")).strip()[:500]  # giới hạn độ dài

    return decision, confidence_score, analysis


# ── Core analyzer ─────────────────────────────────────────────────────────────

async def _call_gemini_with_retry(
    client,
    user_prompt:     str,
    timeout_seconds: float,
) -> str:
    """Gọi Gemini API với retry khi gặp rate limit.

    Dùng exponential backoff theo _RATE_LIMIT_RETRY_DELAYS khi gặp 429.
    Các lỗi khác (network, timeout) raise ngay lập tức.

    Args:
        client: google.generativeai.GenerativeModel instance.
        user_prompt: User prompt đã được build.
        timeout_seconds: Timeout cho mỗi attempt.

    Returns:
        Raw text response từ Gemini.

    Raises:
        Exception: Nếu hết retry hoặc gặp lỗi không phải rate limit.
    """
    last_exc: Optional[Exception] = None

    for attempt, delay in enumerate([0.0] + _RATE_LIMIT_RETRY_DELAYS, start=1):
        if delay > 0:
            logger.warning(
                f"[AIAnalyzer] Rate limit, retry {attempt}/{len(_RATE_LIMIT_RETRY_DELAYS) + 1} "
                f"sau {delay:.0f}s..."
            )
            await asyncio.sleep(delay)

        try:
            response = await asyncio.wait_for(
                client.generate_content_async(user_prompt),
                timeout=timeout_seconds,
            )
            return response.text

        except asyncio.TimeoutError:
            raise  # Timeout không retry — raise ngay

        except Exception as exc:
            err_str = str(exc).lower()
            is_rate_limit = any(k in err_str for k in ("429", "quota", "rate limit", "resource_exhausted"))
            if is_rate_limit and attempt <= len(_RATE_LIMIT_RETRY_DELAYS):
                last_exc = exc
                continue  # Retry
            raise  # Lỗi khác hoặc hết retry → raise

    raise last_exc  # type: ignore[misc]


async def analyze_signal(
    signal_type:    str,
    symbol:         str,
    strategy_name:  str,
    signal_reason:  str,
    ohlcv:          list,
    current_price:  float,
    timeframe:      str,
    metadata:       dict,
    indicator_data: dict,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    min_confidence:  int   = _DEFAULT_MIN_CONFIDENCE,
) -> AIAnalysisResult:
    """Phân tích tín hiệu giao dịch bằng Gemini AI.

    Fail-open: Mọi lỗi (API unavailable, timeout, parse error, rate limit)
    đều trả về decision="skip" thay vì raise exception.
    BotEngine sẽ tiếp tục đặt lệnh bình thường khi decision="skip".

    Rate limit: Dùng _global_ai_semaphore để giới hạn concurrent calls.

    Args:
        signal_type: "long" hoặc "short".
        symbol: Symbol giao dịch (vd: "BTC/USDT").
        strategy_name: Tên chiến lược.
        signal_reason: Lý do signal từ strategy.
        ohlcv: Dữ liệu nến OHLCV [[ts, o, h, l, c, v], ...].
        current_price: Giá hiện tại.
        timeframe: Timeframe (vd: "5m").
        metadata: Metadata từ strategy (trend, momentum, slope, ...).
        indicator_data: Dict chứa ma_fast, ma_slow, macd, macd_signal, ...
        timeout_seconds: Timeout cho Gemini API call.
        min_confidence: Reject nếu confidence < min_confidence dù AI approve.

    Returns:
        AIAnalysisResult với decision, confidence_score, analysis.
        decision="skip" nếu AI không khả dụng.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return AIAnalysisResult(
            decision="skip",
            confidence_score=0,
            analysis="",
            skipped_reason="GEMINI_API_KEY chua duoc cau hinh",
        )

    t0 = time.perf_counter()

    try:
        import google.generativeai as genai

        # ── Few-shot: fetch dislike examples theo strategy ────────────────────
        # Fail-open: nếu DB lỗi → examples = [] → dùng prompt mặc định
        examples = await _fetch_dislike_examples(strategy_name)
        few_shot_section = _build_few_shot_section(examples)

        logger.info(
            f"[AIAnalyzer] Phan tich {symbol} {signal_type.upper()} "
            f"| Strategy: {strategy_name} "
            f"| {len(examples)} historical lesson(s) loaded"
        )

        # ── Build dynamic system prompt ───────────────────────────────────────
        # Base prompt + few-shot section (rỗng nếu không có examples)
        dynamic_system_prompt = _SYSTEM_PROMPT + few_shot_section

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=_GEMINI_MODEL,
            system_instruction=dynamic_system_prompt,
        )

        user_prompt = _build_user_prompt(
            signal_type=signal_type,
            symbol=symbol,
            strategy_name=strategy_name,
            signal_reason=signal_reason,
            ohlcv=ohlcv,
            current_price=current_price,
            timeframe=timeframe,
            metadata=metadata,
            indicator_data=indicator_data,
        )

        # Acquire semaphore để giới hạn concurrent calls
        async with _global_ai_semaphore:
            raw_text = await _call_gemini_with_retry(model, user_prompt, timeout_seconds)

        latency_ms = (time.perf_counter() - t0) * 1000
        decision, confidence_score, analysis = _parse_gemini_response(raw_text)

        # Áp dụng min_confidence filter
        if decision == "approve" and confidence_score < min_confidence:
            logger.info(
                f"[AIAnalyzer] {symbol} {signal_type.upper()} — "
                f"Approve nhung confidence={confidence_score} < min={min_confidence} "
                f"→ chuyen thanh reject"
            )
            decision = "reject"
            analysis = (
                f"[Low confidence: {confidence_score}/{min_confidence}] {analysis}"
            )

        logger.info(
            f"[AIAnalyzer] {symbol} {signal_type.upper()} → "
            f"{decision.upper()} (confidence={confidence_score}) "
            f"| {analysis[:80]} "
            f"| latency={latency_ms:.0f}ms"
        )

        return AIAnalysisResult(
            decision=decision,
            confidence_score=confidence_score,
            analysis=analysis,
            raw_response=raw_text[:1000],
            latency_ms=latency_ms,
        )

    except asyncio.TimeoutError:
        latency_ms = (time.perf_counter() - t0) * 1000
        reason = f"Timeout sau {timeout_seconds:.0f}s"
        logger.warning(f"[AIAnalyzer] {symbol} {signal_type.upper()} — {reason} → skip")
        return AIAnalysisResult(
            decision="skip",
            confidence_score=0,
            analysis="",
            latency_ms=latency_ms,
            skipped_reason=reason,
        )

    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning(
            f"[AIAnalyzer] {symbol} {signal_type.upper()} — LOI: {reason} → skip\n"
            f"{traceback.format_exc()[-500:]}"
        )
        return AIAnalysisResult(
            decision="skip",
            confidence_score=0,
            analysis="",
            latency_ms=latency_ms,
            skipped_reason=reason,
        )
