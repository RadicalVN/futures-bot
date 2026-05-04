"""Chay backtest V2 (bot_id=9) cung thoi gian voi V1 (20/04-30/04)"""
import asyncio, sys, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

async def main():
    from src.database.db import init_db, get_db
    from src.database.models import Bot, ExchangeAccount
    from src.core.exchange import BinanceExchange
    from src.dashboard.routers.backtest import _run_backtest_engine
    from sqlalchemy import select
    from datetime import datetime, timezone

    await init_db()
    async with get_db() as db:
        r = await db.execute(select(Bot).where(Bot.id == 9))
        bot = r.scalar_one_or_none()
        account = None
        if bot.account_id:
            r2 = await db.execute(select(ExchangeAccount).where(ExchangeAccount.id == bot.account_id))
            account = r2.scalar_one_or_none()

    sys.stdout.write(f"Bot: {bot.name} | strategy={bot.strategy_name}\n")
    sys.stdout.write(f"Params: bb_length={bot.parameters.get('bb_length')} use_trend_filter={bot.parameters.get('use_trend_filter')}\n")

    start_ms = int(datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms   = int(datetime(2026, 4, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

    exchange = BinanceExchange(account.api_key, account.api_secret, account.mode, "futures")
    await exchange.connect()
    try:
        result = await _run_backtest_engine(bot=bot, exchange=exchange, start_ms=start_ms, end_ms=end_ms, initial_balance=10000.0)
    finally:
        await exchange.close()

    s = result["summary"]
    sys.stdout.write(f"\n=== KET QUA V2 ===\n")
    sys.stdout.write(f"Tong lenh:    {s['total_trades']}\n")
    sys.stdout.write(f"Thang/Thua:   {s['winning_trades']}/{s['losing_trades']}\n")
    sys.stdout.write(f"Win rate:     {s['win_rate']}%\n")
    sys.stdout.write(f"Tong PnL:     {s['total_pnl']} USDT\n")
    sys.stdout.write(f"Return:       {s['total_return_pct']}%\n")
    sys.stdout.write(f"Max DD:       {s['max_drawdown_pct']}%\n")
    sys.stdout.write(f"Profit Factor:{s['profit_factor']}\n")
    sys.stdout.write(f"Sharpe:       {s['sharpe_ratio']}\n")
    sys.stdout.write(f"TB thang:     {s['avg_win']} USDT\n")
    sys.stdout.write(f"TB thua:      {s['avg_loss']} USDT\n")
    sys.stdout.write(f"TB hold:      {s['avg_holding_candles']} nen\n")
    sys.stdout.write(f"\n=== CHI TIET LENH ===\n")
    for t in result["trades"]:
        mark = "+" if t["pnl"] > 0 else "-"
        sys.stdout.write(f"  {mark} {t['entry_time']}->{t['exit_time']} {t['side'].upper()} entry={t['entry_price']:.2f} exit={t['exit_price']:.2f} pnl={t['pnl']:.4f}({t['pnl_pct']:+.2f}%) hold={t['holding_candles']}n\n")

asyncio.run(main())
