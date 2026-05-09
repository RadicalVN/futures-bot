"""
analytics.py — FastAPI router cho Performance Analytics API.

Router chi dieu phoi — khong chua logic tinh toan.
Moi logic duoc delegate sang src.apps.analytics.service.

Endpoints:
    GET /api/analytics/bots                  → Hieu suat tat ca bot
    GET /api/analytics/bots/{bot_id}         → Hieu suat 1 bot (404 neu khong tim thay)
    GET /api/analytics/strategies/{name}     → Hieu suat tong hop theo strategy
"""
from fastapi import APIRouter, HTTPException, Query

from src.apps.analytics.service import (
    get_all_bots_performance,
    get_bot_performance,
    get_strategy_performance,
)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/bots")
async def list_bots_performance(
    days: int = Query(default=30, ge=1, le=365, description="So ngay nhin lai"),
) -> list[dict]:
    """Tra ve danh sach hieu suat cua tat ca bot trong N ngay gan nhat.

    Args:
        days: So ngay nhin lai (1-365, default: 30).

    Returns:
        List[dict] moi phan tu chua day du chi so hieu suat cua 1 bot.
        Danh sach rong neu khong co bot nao.

    Example response:
        [
            {
                "bot_id": 7,
                "bot_name": "TVT-SMA_MACD BTCUSDT",
                "strategy_name": "sma_macd_cross_v7",
                "period_days": 30,
                "total_trades": 25,
                "winning_trades": 17,
                "win_rate_pct": 68.0,
                "net_pnl": 142.50,
                "profit_factor": 2.1,
                "max_drawdown": 45.20,
                ...
            }
        ]
    """
    performances = await get_all_bots_performance(days=days)
    return [p.to_dict() for p in performances]


@router.get("/bots/{bot_id}")
async def get_bot_performance_detail(
    bot_id: int,
    days:   int = Query(default=30, ge=1, le=365, description="So ngay nhin lai"),
) -> dict:
    """Tra ve hieu suat chi tiet cua 1 bot trong N ngay gan nhat.

    Args:
        bot_id: ID cua bot can xem.
        days: So ngay nhin lai (1-365, default: 30).

    Returns:
        Dict chua day du chi so hieu suat cua bot.

    Raises:
        HTTPException 404: Neu bot khong ton tai.

    Example response:
        {
            "bot_id": 7,
            "bot_name": "TVT-SMA_MACD BTCUSDT",
            "strategy_name": "sma_macd_cross_v7",
            "period_days": 30,
            "computed_at": "2026-05-10T01:00:00",
            "total_trades": 25,
            "winning_trades": 17,
            "losing_trades": 8,
            "win_rate_pct": 68.0,
            "net_pnl": 142.50,
            "gross_profit": 210.00,
            "gross_loss": 67.50,
            "profit_factor": 3.11,
            "max_drawdown": 45.20,
            "avg_duration_hours": 3.5,
            "best_trade": 38.20,
            "worst_trade": -22.10
        }
    """
    performance = await get_bot_performance(bot_id=bot_id, days=days)
    if performance is None:
        raise HTTPException(
            status_code=404,
            detail=f"Bot #{bot_id} khong ton tai hoac da bi xoa",
        )
    return performance.to_dict()


@router.get("/strategies/{name}")
async def get_strategy_performance_detail(
    name: str,
    days: int = Query(default=30, ge=1, le=365, description="So ngay nhin lai"),
) -> dict:
    """Tra ve hieu suat tong hop cua 1 strategy tren tat ca bot.

    Gop tat ca lenh cua strategy nay tu moi bot lai de tinh metrics chung.
    Huu ich de so sanh hieu qua giua cac phien ban strategy (v1, v2, ..., v7).

    Args:
        name: Ten strategy (vd: "sma_macd_cross_v7", "adts", "ma_macd").
        days: So ngay nhin lai (1-365, default: 30).

    Returns:
        Dict chua chi so hieu suat tong hop cua strategy.
        Tra ve metrics rong (total_trades=0) neu strategy chua co lenh nao.

    Example response:
        {
            "strategy_name": "sma_macd_cross_v7",
            "period_days": 30,
            "bot_count": 2,
            "computed_at": "2026-05-10T01:00:00",
            "total_trades": 43,
            "winning_trades": 28,
            "win_rate_pct": 65.1,
            "net_pnl": 285.30,
            "profit_factor": 2.8,
            "max_drawdown": 67.40,
            ...
        }
    """
    performance = await get_strategy_performance(strategy_name=name, days=days)
    if performance is None:
        raise HTTPException(
            status_code=500,
            detail=f"Loi khi tinh hieu suat strategy '{name}'",
        )
    return performance.to_dict()
