import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot
    from sqlalchemy import select
    await init_db()
    async with get_db() as db:
        r = await db.execute(select(Bot).where(Bot.id == 7))
        bot7 = r.scalar_one_or_none()

        r2 = await db.execute(select(Bot).where(Bot.strategy_name == "sma_macd_cross_v3"))
        existing = r2.scalar_one_or_none()
        if existing:
            sys.stdout.write(f"EXISTS id={existing.id}\n")
            return

        params_v3 = dict(bot7.parameters or {})
        params_v3["bb_length"] = 200
        params_v3["use_trend_filter"] = True
        params_v3["min_ma_distance_pct"] = 0.1
        params_v3["min_hold_candles"] = 3

        bot_v3 = Bot(
            name="TVT-SMA+MACD-V3 / BTCUSDT",
            account_id=bot7.account_id,
            symbols=["BTCUSDT"],
            strategy_name="sma_macd_cross_v3",
            parameters=params_v3,
            status="stopped",
        )
        db.add(bot_v3)
        await db.flush()
        sys.stdout.write(f"CREATED id={bot_v3.id}\n")
        sys.stdout.write(f"bb_length={params_v3['bb_length']}\n")
        sys.stdout.write(f"use_trend_filter={params_v3['use_trend_filter']}\n")
        sys.stdout.write(f"min_ma_distance_pct={params_v3['min_ma_distance_pct']}\n")
        sys.stdout.write(f"min_hold_candles={params_v3['min_hold_candles']}\n")

asyncio.run(main())
