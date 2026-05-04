"""Tạo bot V2 trong DB để backtest"""
import asyncio, sys
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot
    from sqlalchemy import select

    await init_db()
    async with get_db() as db:
        # Lấy params từ bot#7 làm base
        r = await db.execute(select(Bot).where(Bot.id == 7))
        bot7 = r.scalar_one_or_none()
        params_v1 = dict(bot7.parameters or {})

        # V2 params: bb_length=150, use_trend_filter=True
        params_v2 = dict(params_v1)
        params_v2["bb_length"] = 150
        params_v2["use_trend_filter"] = True

        # Kiểm tra đã có bot V2 chưa
        r2 = await db.execute(select(Bot).where(Bot.name == "TVT-SMA+MACD-V2 / BTCUSDT"))
        existing = r2.scalar_one_or_none()
        if existing:
            print(f"Bot V2 đã tồn tại: ID={existing.id}")
            return existing.id

        bot_v2 = Bot(
            name="TVT-SMA+MACD-V2 / BTCUSDT",
            account_id=bot7.account_id,
            symbols=["BTCUSDT"],
            strategy_name="sma_macd_cross_v2",
            parameters=params_v2,
            status="stopped",
        )
        db.add(bot_v2)
        await db.flush()
        bot_id = bot_v2.id
        print(f"Đã tạo Bot V2: ID={bot_id}")
        print(f"Params V1: bb_length={params_v1.get('bb_length',50)}, use_trend_filter=False")
        print(f"Params V2: bb_length={params_v2['bb_length']}, use_trend_filter=True")
        return bot_id

asyncio.run(main())
