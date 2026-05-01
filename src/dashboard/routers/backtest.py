import os
import math
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from loguru import logger

from src.database.db import get_db
from src.database.models import Bot, ExchangeAccount
from src.core.exchange import BinanceExchange, create_exchange_from_env
from src.strategies.ma_macd import MaMacdStrategy
from src.strategies.custom_sma import CustomSMAStrategy
from src.strategies.custom_macd import CustomMACDStrategy
from src.strategies.sma_trend_early_exit import SmaTrendEarlyExitStrategy
from src.strategies.sma_pullback import SmaPullbackStrategy
from src.strategies.sma_anti_sideway import SmaAntiSidewayStrategy
from src.strategies.sma_macd_cross import SmaMacdCrossStrategy
router = APIRouter(prefix='/api/backtest', tags=['Backtest'])
BACKTEST_DIR = 'data/backtest'
COMMISSION = 0.0005
UTC7 = timezone(timedelta(hours=7))


class BacktestRequest(BaseModel):
    bot_id: int
    start_date: str
    end_date: Optional[str] = None
    initial_balance: float = 10000.0
    timeframe: Optional[str] = None  # None = dùng timeframe của bot


def _timeframe_ms(tf):
    units = {"m": 60000, "h": 3600000, "d": 86400000, "w": 604800000}
    try:
        return int(tf[:-1]) * units[tf[-1]]
    except Exception:
        return 300000


def _build_strategy(strategy_name, parameters):
    if strategy_name == "ma_macd":
        return MaMacdStrategy(parameters)
    elif strategy_name == "custom_sma":
        return CustomSMAStrategy(parameters)
    elif strategy_name == "custom_macd":
        return CustomMACDStrategy(parameters)
    elif strategy_name == "sma_trend_early_exit":
        return SmaTrendEarlyExitStrategy(parameters)
    elif strategy_name == "sma_pullback":
        return SmaPullbackStrategy(parameters)
    elif strategy_name == "sma_anti_sideway":
        return SmaAntiSidewayStrategy(parameters)
    elif strategy_name == "sma_macd_cross":
        return SmaMacdCrossStrategy(parameters)
    else:
        raise ValueError(f"Unsupported strategy: {strategy_name}")


def _get_lookback(strategy_name, parameters):
    base = parameters.get("lookback_candles", 200)
    if strategy_name == "sma_macd_cross":
        return max(base, int(parameters.get("macd_signal_length", 500)) + 50)
    elif strategy_name == "custom_macd":
        return max(base, int(parameters.get("signal_length", 500)) + 50)
    return base


def _normalize_symbol(symbol):
    if "/" in symbol:
        return symbol
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
    return symbol


def _to_utc7_str(ts_ms):
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC7)
    return dt.strftime("%Y-%m-%d %H:%M")


async def _fetch_ohlcv_range(exchange, symbol, timeframe, start_ms, end_ms):
    """Fetch OHLCV từ start_ms đến end_ms, paginate ngược nếu cần."""
    all_candles = []
    current_end = end_ms
    max_iterations = 50  # safety cap
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        batch = await exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, limit=1500,
            params={'endTime': current_end}
        )
        if not batch:
            break

        # Prepend batch (older candles go first)
        all_candles = batch + all_candles
        oldest_ts = batch[0][0]

        if oldest_ts <= start_ms:
            break  # Đã có đủ dữ liệu từ start_ms trở đi

        current_end = oldest_ts - 1
        if current_end < start_ms:
            break

    # Deduplicate và sort
    seen = set()
    result = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            result.append(c)
    result.sort(key=lambda x: x[0])
    return result


async def _run_backtest_engine(bot, exchange, start_ms, end_ms, initial_balance, timeframe_override=None):
    strategy_name = bot.strategy_name
    parameters = bot.parameters or {}
    # Dùng timeframe override nếu có, fallback về timeframe của bot
    timeframe = timeframe_override or parameters.get("timeframe", "5m")
    leverage = int(parameters.get("leverage", 5))
    position_size_pct = float(parameters.get("position_size_pct", 0.10))
    lookback = _get_lookback(strategy_name, parameters)
    strategy = _build_strategy(strategy_name, parameters)
    symbols_raw = bot.symbols or ["BTCUSDT"]
    symbol_raw = symbols_raw[0] if symbols_raw else "BTCUSDT"
    symbol = _normalize_symbol(symbol_raw)

    logger.info(f"Backtest: fetching OHLCV for {symbol} {timeframe} from {start_ms} to {end_ms}")
    tf_ms = _timeframe_ms(timeframe)

    # Fetch từ warmup_start để có đủ nến cho indicator
    warmup_start_ms = start_ms - (lookback * tf_ms * 2)
    all_candles = await _fetch_ohlcv_range(exchange, symbol, timeframe, warmup_start_ms, end_ms)

    if len(all_candles) < lookback + 10:
        raise ValueError(
            f"Không đủ dữ liệu: có {len(all_candles)} nến, cần ít nhất {lookback + 10}. "
            f"Thử chọn khoảng thời gian dài hơn."
        )
    logger.info(f"Backtest: fetched {len(all_candles)} candles total (warmup included)")

    # Tìm index nến đầu tiên >= start_ms (bắt đầu simulate từ đây)
    start_idx = lookback  # mặc định: đủ warmup
    for i, c in enumerate(all_candles):
        if c[0] >= start_ms and i >= lookback:
            start_idx = i
            break
    # Nếu không tìm thấy nến nào >= start_ms trong range, dùng lookback
    if start_idx < lookback:
        start_idx = lookback
    balance = initial_balance
    open_position = None
    trades = []
    equity_curve = [{"ts": all_candles[start_idx][0], "balance": balance, "pnl_cum": 0.0, "drawdown_pct": 0.0}]
    peak_balance = balance
    for i in range(start_idx, len(all_candles)):
        candle = all_candles[i]
        ts_ms = candle[0]
        if ts_ms > end_ms:
            break
        ohlcv_slice = all_candles[max(0, i - lookback * 2): i + 1]
        if open_position:
            sim_positions = [{"symbol": symbol, "side": open_position["side"], "size": open_position["size"], "entry_price": open_position["entry_price"], "metadata": open_position.get("metadata", {})}]
        else:
            sim_positions = []
        try:
            signal = await strategy.analyze(symbol, ohlcv_slice, sim_positions)
        except Exception as e:
            logger.warning(f"Strategy error at candle {i}: {e}")
            continue
        if signal.is_entry and open_position is None:
            entry_price = signal.price if signal.price and signal.price > 0 else candle[4]
            position_value = balance * position_size_pct * leverage
            size = position_value / entry_price
            fee = position_value * COMMISSION
            open_position = {"side": signal.signal, "entry_price": entry_price, "size": size, "position_value": position_value, "entry_fee": fee, "entry_ts": ts_ms, "entry_candle_idx": i, "metadata": signal.metadata or {}}
            balance -= fee
        elif signal.is_exit and open_position is not None:
            exit_price = signal.price if signal.price and signal.price > 0 else candle[4]
            pos = open_position
            position_value = pos["position_value"]
            size = pos["size"]
            if pos["side"] == "long":
                price_change_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
            else:
                price_change_pct = (pos["entry_price"] - exit_price) / pos["entry_price"]
            gross_pnl = position_value * price_change_pct
            exit_fee = position_value * COMMISSION
            net_pnl = gross_pnl - pos["entry_fee"] - exit_fee
            pnl_pct = net_pnl / (position_value / leverage) * 100
            balance += net_pnl
            holding_candles = i - pos["entry_candle_idx"]
            trade = {
                "entry_time": _to_utc7_str(pos["entry_ts"]),
                "exit_time":  _to_utc7_str(ts_ms),
                "entry_ts_ms": pos["entry_ts"],   # giữ lại ms cho equity chart
                "exit_ts_ms":  ts_ms,
                "symbol": symbol,
                "side": pos["side"],
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "size": size,
                "pnl": round(net_pnl, 4),
                "pnl_pct": round(pnl_pct, 2),
                "balance_after": round(balance, 4),
                "holding_candles": holding_candles,
            }
            trades.append(trade)
            pnl_cum = balance - initial_balance
            peak_balance = max(peak_balance, balance)
            drawdown_pct = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0.0
            equity_curve.append({"ts": ts_ms, "balance": round(balance, 4), "pnl_cum": round(pnl_cum, 4), "drawdown_pct": round(drawdown_pct, 2)})
            open_position = None

    total_trades = len(trades)
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    win_count = len(winning)
    loss_count = len(losing)
    win_rate = round(win_count / total_trades * 100, 2) if total_trades > 0 else 0.0
    total_pnl = sum(t["pnl"] for t in trades)
    total_return_pct = round((balance - initial_balance) / initial_balance * 100, 2)
    gross_profit = sum(t["pnl"] for t in winning)
    gross_loss = abs(sum(t["pnl"] for t in losing))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else 999.0  # cap Infinity để JSON serialize được
    avg_win = round(gross_profit / win_count, 4) if win_count > 0 else 0.0
    avg_loss = round(-gross_loss / loss_count, 4) if loss_count > 0 else 0.0
    largest_win = round(max((t["pnl"] for t in winning), default=0.0), 4)
    largest_loss = round(min((t["pnl"] for t in losing), default=0.0), 4)
    avg_holding = round(sum(t["holding_candles"] for t in trades) / total_trades, 1) if total_trades > 0 else 0.0
    peak = initial_balance
    max_dd = 0.0
    running_bal = initial_balance
    for t in trades:
        running_bal = t["balance_after"]
        peak = max(peak, running_bal)
        dd = (peak - running_bal) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    max_drawdown_pct = round(max_dd, 2)
    if len(trades) > 1:
        returns = [t["pnl_pct"] / 100 for t in trades]
        mean_r = sum(returns) / len(returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns))
        tf_per_day = 86400_000 / _timeframe_ms(timeframe)
        annual_factor = math.sqrt(tf_per_day * 252)
        sharpe = round((mean_r / std_r * annual_factor) if std_r > 0 else 0.0, 3)
    else:
        sharpe = 0.0
    summary = {"total_trades": total_trades, "winning_trades": win_count, "losing_trades": loss_count, "win_rate": win_rate, "total_pnl": round(total_pnl, 4), "total_return_pct": total_return_pct, "max_drawdown_pct": max_drawdown_pct, "profit_factor": profit_factor, "avg_win": avg_win, "avg_loss": avg_loss, "largest_win": largest_win, "largest_loss": largest_loss, "avg_holding_candles": avg_holding, "sharpe_ratio": sharpe, "initial_balance": initial_balance, "final_balance": round(balance, 4)}
    return {"symbol": symbol, "timeframe": timeframe, "trades": trades, "equity_curve": equity_curve, "summary": summary}


def _create_excel(bot, result, start_date, end_date, filepath):
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError("openpyxl is required. Run: pip install openpyxl>=3.1.2")

    # Đảm bảo thư mục tồn tại
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    wb = openpyxl.Workbook()
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    alt_fill = PatternFill(start_color="DEEAF1", end_color="DEEAF1", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    bold_font = Font(bold=True)
    summary = result["summary"]
    trades = result["trades"]
    equity_curve = result["equity_curve"]
    symbol = result["symbol"]
    timeframe = result["timeframe"]
    ws1 = wb.active
    ws1.title = "Tong hop"
    ws1.column_dimensions["A"].width = 32
    ws1.column_dimensions["B"].width = 25
    info_rows = [("THONG TIN BOT", ""), ("Ten bot", bot.name), ("Chien luoc", bot.strategy_name), ("Symbol", symbol), ("Timeframe", timeframe), ("Tu ngay", start_date), ("Den ngay", end_date), ("Von ban dau (USDT)", summary["initial_balance"]), ("", ""), ("KET QUA BACKTEST", ""), ("Tong so lenh", summary["total_trades"]), ("Lenh thang", summary["winning_trades"]), ("Lenh thua", summary["losing_trades"]), ("Ti le thang (%)", summary["win_rate"]), ("Tong Pnl (USDT)", summary["total_pnl"]), ("Tong loi nhuan (%)", summary["total_return_pct"]), ("Von cuoi (USDT)", summary["final_balance"]), ("Max Drawdown (%)", summary["max_drawdown_pct"]), ("Profit Factor", summary["profit_factor"]), ("TB lenh thang (USDT)", summary["avg_win"]), ("TB lenh thua (USDT)", summary["avg_loss"]), ("Lenh thang lon nhat (USDT)", summary["largest_win"]), ("Lenh thua lon nhat (USDT)", summary["largest_loss"]), ("TB thoi gian giu (nen)", summary["avg_holding_candles"]), ("Sharpe Ratio", summary["sharpe_ratio"])]
    for row_idx, (label, value) in enumerate(info_rows, start=1):
        cell_a = ws1.cell(row=row_idx, column=1, value=label)
        cell_b = ws1.cell(row=row_idx, column=2, value=value)
        if label in ("THONG TIN BOT", "KET QUA BACKTEST"):
            cell_a.font = header_font
            cell_a.fill = header_fill
            cell_b.fill = header_fill
        elif label:
            cell_a.font = bold_font
            if isinstance(value, (int, float)):
                pos_labels = ("Tong Pnl (USDT)", "Tong loi nhuan (%)", "Von cuoi (USDT)", "Profit Factor", "Sharpe Ratio", "TB lenh thang (USDT)", "Lenh thang lon nhat (USDT)")
                neg_labels = ("Max Drawdown (%)", "TB lenh thua (USDT)", "Lenh thua lon nhat (USDT)")
                if label in pos_labels:
                    cell_b.fill = green_fill if value >= 0 else red_fill
                elif label in neg_labels:
                    cell_b.fill = red_fill if value != 0 else green_fill
    ws2 = wb.create_sheet("Chi tiet lenh")
    headers2 = ["#", "Thoi gian vao", "Thoi gian ra", "Symbol", "Side", "Gia vao", "Gia ra", "So luong", "Pnl (USDT)", "Pnl (%)", "So du sau lenh", "Thoi gian giu (nen)"]
    col_widths2 = [5, 18, 18, 12, 8, 14, 14, 12, 14, 10, 16, 18]
    for col_idx, (h, w) in enumerate(zip(headers2, col_widths2), start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws2.column_dimensions[get_column_letter(col_idx)].width = w
    for t_idx, trade in enumerate(trades, start=1):
        row = t_idx + 1
        fill = alt_fill if t_idx % 2 == 0 else None
        pnl_fill = green_fill if trade["pnl"] > 0 else red_fill
        values = [t_idx, trade["entry_time"], trade["exit_time"], trade["symbol"], trade["side"].upper(), trade["entry_price"], trade["exit_price"], round(trade["size"], 4), trade["pnl"], trade["pnl_pct"], trade["balance_after"], trade["holding_candles"]]
        for col_idx, val in enumerate(values, start=1):
            cell = ws2.cell(row=row, column=col_idx, value=val)
            if col_idx in (9, 10):
                cell.fill = pnl_fill
            elif fill:
                cell.fill = fill
    ws3 = wb.create_sheet("Duong von")
    headers3 = ["Thoi gian", "So du", "Pnl tich luy", "Drawdown (%)"]
    col_widths3 = [18, 16, 16, 14]
    for col_idx, (h, w) in enumerate(zip(headers3, col_widths3), start=1):
        cell = ws3.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws3.column_dimensions[get_column_letter(col_idx)].width = w
    for eq_idx, eq in enumerate(equity_curve, start=1):
        row = eq_idx + 1
        fill = alt_fill if eq_idx % 2 == 0 else None
        pnl_fill = green_fill if eq["pnl_cum"] >= 0 else red_fill
        dd_fill = red_fill if eq["drawdown_pct"] > 5 else (alt_fill if eq["drawdown_pct"] > 0 else None)
        cells_data = [(1, _to_utc7_str(eq["ts"]), fill), (2, eq["balance"], fill), (3, eq["pnl_cum"], pnl_fill), (4, eq["drawdown_pct"], dd_fill)]
        for col_idx, val, f in cells_data:
            cell = ws3.cell(row=row, column=col_idx, value=val)
            if f:
                cell.fill = f
    wb.save(filepath)
    logger.info(f"Excel saved: {filepath}")


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    try:
        async with get_db() as db:
            result = await db.execute(select(Bot).where(Bot.id == req.bot_id, Bot.is_deleted == False))
            bot = result.scalar_one_or_none()
            if not bot:
                raise HTTPException(status_code=404, detail=f"Bot ID={req.bot_id} not found")
            account = None
            if bot.account_id:
                acc_result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.id == bot.account_id))
                account = acc_result.scalar_one_or_none()
        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ms = int(start_dt.timestamp() * 1000)
        if req.end_date:
            end_dt = datetime.strptime(req.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = datetime.now(timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000)
        end_date_str = end_dt.strftime("%Y-%m-%d")
        parameters = bot.parameters or {}
        market_type = parameters.get("market_type", "futures")
        if account:
            exchange = BinanceExchange(api_key=account.api_key, api_secret=account.api_secret, mode=account.mode, market_type=market_type)
        else:
            exchange = create_exchange_from_env()
            exchange.market_type = market_type
        try:
            await exchange.connect()
            result = await _run_backtest_engine(
                bot=bot, exchange=exchange,
                start_ms=start_ms, end_ms=end_ms,
                initial_balance=req.initial_balance,
                timeframe_override=req.timeframe or None,
            )
        finally:
            await exchange.close()
        symbol_safe = result["symbol"].replace("/", "")
        tf_safe     = result["timeframe"].replace("m", "m").replace("h", "h")
        start_safe  = req.start_date.replace("-", "")
        end_safe    = end_date_str.replace("-", "")
        filename = f"backtest_{req.bot_id}_{symbol_safe}_{tf_safe}_{start_safe}_{end_safe}.xlsx"
        filepath = os.path.join(BACKTEST_DIR, filename)
        _create_excel(bot=bot, result=result, start_date=req.start_date, end_date=end_date_str, filepath=filepath)
        return {"success": True, "bot_id": req.bot_id, "bot_name": bot.name, "symbol": result["symbol"], "timeframe": result["timeframe"], "start_date": req.start_date, "end_date": end_date_str, "initial_balance": req.initial_balance, "summary": result["summary"], "trades": result["trades"], "equity_curve": result["equity_curve"], "excel_filename": filename, "download_url": f"/api/backtest/download/{filename}"}
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Backtest validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Backtest error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Backtest failed: {type(e).__name__}: {str(e)}")


@router.get("/download/{filename}")
async def download_backtest(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(BACKTEST_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(path=filepath, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
