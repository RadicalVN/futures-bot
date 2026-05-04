import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot
    from sqlalchemy import select
    await init_db()
    async with get_db() as db:
        r = await db.execute(select(Bot).where(Bot.id == 11))
        bot = r.scalar_one_or_none()
        params = dict(bot.parameters or {})
        params["leverage_v4"]     = 10
        params["notional_usdt"]   = 2000.0
        params["stop_loss_pct"]   = 3.0
        params["take_profit_pct"] = 3.0
        # Xoa leverage/position_size_pct cu de tranh nham
        params.pop("leverage", None)
        params.pop("position_size_pct", None)
        bot.parameters = params
        sys.stdout.write(f"Bot#{bot.id} updated: leverage_v4={params['leverage_v4']} notional=${params['notional_usdt']} SL={params['stop_loss_pct']}% TP={params['take_profit_pct']}%\n")

asyncio.run(main())
