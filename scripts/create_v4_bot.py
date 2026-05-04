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

        r2 = await db.execute(select(Bot).where(Bot.strategy_name == "sma_macd_cross_v4"))
        existing = r2.scalar_one_or_none()
        if existing:
            sys.stdout.write(f"EXISTS id={existing.id}\n")
            return

        params_v4 = dict(bot7.parameters or {})
        params_v4["stop_loss_pct"]   = 3.0
        params_v4["take_profit_pct"] = 3.0

        bot_v4 = Bot(
            name="TVT-SMA+MACD-V4 / BTCUSDT",
            account_id=bot7.account_id,
            symbols=["BTCUSDT"],
            strategy_name="sma_macd_cross_v4",
            parameters=params_v4,
            status="stopped",
        )
        db.add(bot_v4)
        await db.flush()
        sys.stdout.write(f"CREATED id={bot_v4.id} SL={params_v4['stop_loss_pct']}% TP={params_v4['take_profit_pct']}%\n")

asyncio.run(main())
