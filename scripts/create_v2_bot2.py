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
        params_v2 = dict(bot7.parameters or {})
        params_v2["bb_length"] = 150
        params_v2["use_trend_filter"] = True

        r2 = await db.execute(select(Bot).where(Bot.strategy_name == "sma_macd_cross_v2"))
        existing = r2.scalar_one_or_none()
        if existing:
            sys.stdout.write(f"EXISTS id={existing.id}\n")
            return

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
        sys.stdout.write(f"CREATED id={bot_v2.id} bb_length={params_v2['bb_length']} trend_filter={params_v2['use_trend_filter']}\n")

asyncio.run(main())
