"""
seed_bots.py — Tạo 6 bots thử nghiệm 3 chiến lược x 2 symbols (BTCUSDT, TRUMPUSDT)

Chạy: python scripts/seed_bots.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.database.db import get_db, init_db
from src.database.models import Bot
from sqlalchemy import select


# ---- Cấu hình 6 bots -------------------------------------------------------
# Tham số dùng chung
BASE_PARAMS = {
    "fast_len": 1,
    "slow_len": 5,
    "len_c": 200,
    "factor": 0.05,
    "bb_length": 50,
    "timeframe": "15m",
    "lookback_candles": 500,
    "check_interval_seconds": 60,
    "market_type": "futures",
    "max_open_positions": 1,   # Mỗi bot chỉ giữ 1 vị thế tại 1 thời điểm
}

BOTS_TO_CREATE = [
    # ── Chiến lược 1: Đánh Thuận Xu Hướng + Thoát Sớm ──────────────────────
    {
        "name": "TVT-EarlyExit / BTCUSDT",
        "account_id": 1,
        "symbols": ["BTCUSDT"],
        "strategy_name": "sma_trend_early_exit",
        "parameters": {**BASE_PARAMS, "min_slope_pct": 0.002},
    },
    {
        "name": "TVT-EarlyExit / TRUMPUSDT",
        "account_id": 1,
        "symbols": ["TRUMPUSDT"],
        "strategy_name": "sma_trend_early_exit",
        "parameters": {**BASE_PARAMS, "min_slope_pct": 0.01},   # TRUMP biến động cao hơn BTC → threshold cao hơn
    },

    # ── Chiến lược 2: Bắt Đáy Sóng Hồi ────────────────────────────────────
    {
        "name": "TVT-Pullback / BTCUSDT",
        "account_id": 1,
        "symbols": ["BTCUSDT"],
        "strategy_name": "sma_pullback",
        "parameters": {**BASE_PARAMS, "pullback_confirm_bars": 2, "min_slope_pct": 0.002},
    },
    {
        "name": "TVT-Pullback / TRUMPUSDT",
        "account_id": 1,
        "symbols": ["TRUMPUSDT"],
        "strategy_name": "sma_pullback",
        "parameters": {**BASE_PARAMS, "pullback_confirm_bars": 3, "min_slope_pct": 0.01},
    },

    # ── Chiến lược 3: Chống Nhiễu Sideway ───────────────────────────────────
    {
        "name": "TVT-AntiSideway / BTCUSDT",
        "account_id": 1,
        "symbols": ["BTCUSDT"],
        "strategy_name": "sma_anti_sideway",
        "parameters": {**BASE_PARAMS, "sideway_slope_threshold": 0.005, "min_momentum_pct": 0.001},
    },
    {
        "name": "TVT-AntiSideway / TRUMPUSDT",
        "account_id": 1,
        "symbols": ["TRUMPUSDT"],
        "strategy_name": "sma_anti_sideway",
        "parameters": {**BASE_PARAMS, "sideway_slope_threshold": 0.015, "min_momentum_pct": 0.005},
    },
]


async def main():
    await init_db()

    async with get_db() as db:
        # Lấy danh sách bot hiện có để tránh tạo duplicate
        result = await db.execute(select(Bot).where(Bot.is_deleted == False))
        existing_names = {b.name for b in result.scalars().all()}

        created = 0
        skipped = 0
        for cfg in BOTS_TO_CREATE:
            if cfg["name"] in existing_names:
                print(f"  [SKIP] Bot '{cfg['name']}' already exists")
                skipped += 1
                continue

            bot = Bot(
                name=cfg["name"],
                account_id=cfg["account_id"],
                symbols=cfg["symbols"],
                strategy_name=cfg["strategy_name"],
                parameters=cfg["parameters"],
                status="stopped",
            )
            db.add(bot)
            created += 1
            print(f"  [OK]   Bot '{cfg['name']}' created")

        await db.commit()
        print(f"\nDone! Created: {created} | Skipped (already exist): {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
