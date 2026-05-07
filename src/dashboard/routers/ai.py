"""
ai.py — FastAPI router cho AI Insights và Feedback Loop.

Endpoints:
    GET  /api/ai/trade/{trade_id}     — Lấy AI analysis của 1 Trade
    POST /api/ai/feedback             — Lưu Like/Dislike của người dùng
    GET  /api/ai/stats                — Thống kê accuracy của AI
    GET  /api/ai/feedback/examples    — Lấy dislike examples cho few-shot prompting
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from src.dashboard.schemas import AIFeedbackCreate
from src.database.db import get_db
from src.database.models import AIFeedback, EntryOpportunity, Trade

router = APIRouter(prefix="/api/ai", tags=["AI Insights"])


# ── GET /api/ai/trade/{trade_id} ──────────────────────────────────────────────

@router.get("/trade/{trade_id}")
async def get_trade_ai_insights(trade_id: int) -> dict:
    """Lấy AI analysis của một Trade từ signal_metadata.

    AI data được lưu trong Trade.signal_metadata với prefix "ai_".
    Endpoint này trích xuất và trả về dạng cấu trúc rõ ràng.

    Args:
        trade_id: ID của Trade cần lấy AI insights.

    Returns:
        Dict chứa ai_insights và feedback hiện tại (nếu có).

    Raises:
        HTTPException 404: Nếu Trade không tồn tại.
    """
    async with get_db() as db:
        result = await db.execute(
            select(Trade)
            .options(selectinload(Trade.ai_feedbacks))
            .where(Trade.id == trade_id)
        )
        trade = result.scalar_one_or_none()

    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade #{trade_id} khong ton tai")

    meta = trade.signal_metadata or {}
    ai_decision = meta.get("ai_decision")

    if not ai_decision:
        return {
            "trade_id":   trade_id,
            "has_ai":     False,
            "ai_insights": None,
            "feedbacks":  [],
        }

    return {
        "trade_id": trade_id,
        "has_ai":   True,
        "ai_insights": {
            "decision":         ai_decision,
            "confidence_score": meta.get("ai_confidence_score"),
            "analysis":         meta.get("ai_analysis"),
            "latency_ms":       meta.get("ai_latency_ms"),
            "skipped_reason":   meta.get("ai_skipped_reason"),
        },
        "feedbacks": [f.to_dict() for f in (trade.ai_feedbacks or [])],
    }


# ── POST /api/ai/feedback ─────────────────────────────────────────────────────

@router.post("/feedback")
async def submit_ai_feedback(feedback_in: AIFeedbackCreate) -> dict:
    """Lưu phản hồi Like/Dislike của người dùng về quyết định AI.

    Tự động snapshot ai_decision và ai_confidence từ Trade.signal_metadata
    để thống kê độc lập sau này.

    Args:
        feedback_in: Pydantic model chứa trade_id, rating, comment.

    Returns:
        Dict xác nhận với id của feedback vừa tạo.

    Raises:
        HTTPException 400: Nếu rating không hợp lệ.
        HTTPException 404: Nếu Trade không tồn tại.
    """
    if feedback_in.rating not in ("like", "dislike"):
        raise HTTPException(
            status_code=400,
            detail=f"rating phai la 'like' hoac 'dislike', got: {feedback_in.rating!r}",
        )

    # Lấy snapshot AI decision từ Trade
    ai_decision   = None
    ai_confidence = None

    if feedback_in.trade_id:
        async with get_db() as db:
            result = await db.execute(
                select(Trade).where(Trade.id == feedback_in.trade_id)
            )
            trade = result.scalar_one_or_none()
            if not trade:
                raise HTTPException(
                    status_code=404,
                    detail=f"Trade #{feedback_in.trade_id} khong ton tai",
                )
            meta          = trade.signal_metadata or {}
            ai_decision   = meta.get("ai_decision")
            ai_confidence = meta.get("ai_confidence_score")

    async with get_db() as db:
        fb = AIFeedback(
            trade_id      = feedback_in.trade_id,
            opp_id        = feedback_in.opp_id,
            rating        = feedback_in.rating,
            comment       = feedback_in.comment,
            ai_decision   = ai_decision,
            ai_confidence = ai_confidence,
        )
        db.add(fb)
        await db.flush()
        fb_id = fb.id

    return {
        "success":     True,
        "feedback_id": fb_id,
        "rating":      feedback_in.rating,
    }


# ── GET /api/ai/stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_ai_stats() -> dict:
    """Thống kê accuracy của AI Analyzer.

    Tính toán:
    - Tổng số lần AI chạy (approve/reject/skip)
    - Win-rate khi AI approve: trong số trade AI approve, bao nhiêu % thắng
    - Accuracy theo feedback: like/(like+dislike)
    - Phân bố decision

    Returns:
        Dict chứa các chỉ số thống kê.
    """
    async with get_db() as db:
        # ── Thống kê từ Trade.signal_metadata ────────────────────────────────
        # Đếm trades có AI data
        all_trades_result = await db.execute(
            select(Trade).where(Trade.signal_metadata.isnot(None))
        )
        all_trades = all_trades_result.scalars().all()

        ai_trades = [
            t for t in all_trades
            if (t.signal_metadata or {}).get("ai_decision") in ("approve", "reject")
        ]

        approve_trades = [
            t for t in ai_trades
            if (t.signal_metadata or {}).get("ai_decision") == "approve"
        ]
        reject_trades = [
            t for t in ai_trades
            if (t.signal_metadata or {}).get("ai_decision") == "reject"
        ]

        # Win-rate khi AI approve (chỉ tính trade đã closed)
        approve_closed = [
            t for t in approve_trades
            if t.status == "closed" and t.realized_pnl is not None
        ]
        approve_wins = [t for t in approve_closed if (t.realized_pnl or 0) > 0]
        approve_win_rate = (
            round(len(approve_wins) / len(approve_closed) * 100, 1)
            if approve_closed else None
        )

        # ── Thống kê từ AIFeedback ────────────────────────────────────────────
        fb_result = await db.execute(select(AIFeedback))
        feedbacks = fb_result.scalars().all()

        total_likes    = sum(1 for f in feedbacks if f.rating == "like")
        total_dislikes = sum(1 for f in feedbacks if f.rating == "dislike")
        total_feedback = total_likes + total_dislikes
        feedback_accuracy = (
            round(total_likes / total_feedback * 100, 1)
            if total_feedback > 0 else None
        )

        # Avg confidence khi approve vs reject
        approve_confidences = [
            (t.signal_metadata or {}).get("ai_confidence_score", 0)
            for t in approve_trades
            if (t.signal_metadata or {}).get("ai_confidence_score") is not None
        ]
        reject_confidences = [
            (t.signal_metadata or {}).get("ai_confidence_score", 0)
            for t in reject_trades
            if (t.signal_metadata or {}).get("ai_confidence_score") is not None
        ]

    return {
        "total_ai_analyzed":    len(ai_trades),
        "total_approve":        len(approve_trades),
        "total_reject":         len(reject_trades),
        "approve_closed":       len(approve_closed),
        "approve_win_rate_pct": approve_win_rate,
        "avg_confidence_approve": (
            round(sum(approve_confidences) / len(approve_confidences), 1)
            if approve_confidences else None
        ),
        "avg_confidence_reject": (
            round(sum(reject_confidences) / len(reject_confidences), 1)
            if reject_confidences else None
        ),
        "total_feedback":       total_feedback,
        "total_likes":          total_likes,
        "total_dislikes":       total_dislikes,
        "feedback_accuracy_pct": feedback_accuracy,
    }


# ── GET /api/ai/feedback/examples ────────────────────────────────────────────

@router.get("/feedback/examples")
async def get_dislike_examples(limit: int = 10) -> list[dict]:
    """Lấy các ví dụ AI sai (dislike) để dùng cho few-shot prompting.

    Trả về danh sách các trường hợp người dùng đánh giá AI sai,
    kèm theo context của trade để đưa vào prompt Gemini.

    Dùng trong tương lai để cải thiện System Prompt:
        "Avoid these mistakes: [examples]"

    Args:
        limit: Số lượng examples tối đa (default 10).

    Returns:
        List dict chứa context trade + AI decision + user comment.
    """
    async with get_db() as db:
        result = await db.execute(
            select(AIFeedback)
            .options(selectinload(AIFeedback.trade))
            .where(AIFeedback.rating == "dislike")
            .order_by(AIFeedback.created_at.desc())
            .limit(limit)
        )
        feedbacks = result.scalars().all()

    examples = []
    for fb in feedbacks:
        trade = fb.trade
        if not trade:
            continue

        meta = trade.signal_metadata or {}
        examples.append({
            "feedback_id":    fb.id,
            "trade_id":       fb.trade_id,
            "symbol":         trade.symbol,
            "signal_type":    trade.signal_type,
            "strategy":       trade.strategy,
            "ai_decision":    fb.ai_decision,
            "ai_confidence":  fb.ai_confidence,
            "ai_analysis":    meta.get("ai_analysis", ""),
            "realized_pnl":   trade.realized_pnl,
            "user_comment":   fb.comment,
            "created_at":     fb.created_at.isoformat() if fb.created_at else None,
            # Few-shot prompt snippet — dùng trực tiếp trong Gemini prompt
            "few_shot_snippet": _build_few_shot_snippet(fb, trade, meta),
        })

    return examples


def _build_few_shot_snippet(
    fb:    AIFeedback,
    trade: Trade,
    meta:  dict,
) -> str:
    """Tạo snippet few-shot cho Gemini prompt từ 1 dislike example.

    Format:
        [MISTAKE EXAMPLE]
        Signal: LONG BTC/USDT | Strategy: sma_macd_cross
        AI said: approve (confidence=75)
        AI analysis: "Strong momentum..."
        Actual result: LOSS (-12.5 USDT)
        User feedback: "AI ignored the bearish divergence on MACD"
        → Lesson: Be more cautious when MACD shows divergence despite bullish signal.

    Args:
        fb: AIFeedback instance.
        trade: Trade instance.
        meta: signal_metadata dict.

    Returns:
        String snippet để đưa vào few-shot prompt.
    """
    pnl = trade.realized_pnl or 0
    result_label = f"WIN (+{pnl:.2f} USDT)" if pnl > 0 else f"LOSS ({pnl:.2f} USDT)"
    comment_line = f"\n        User feedback: \"{fb.comment}\"" if fb.comment else ""

    return (
        f"[MISTAKE EXAMPLE]\n"
        f"        Signal: {(trade.signal_type or '').upper()} {trade.symbol} "
        f"| Strategy: {trade.strategy or 'unknown'}\n"
        f"        AI said: {fb.ai_decision} (confidence={fb.ai_confidence})\n"
        f"        AI analysis: \"{meta.get('ai_analysis', '')[:100]}\"\n"
        f"        Actual result: {result_label}"
        f"{comment_line}"
    )
