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
from src.strategies.sma_macd_cross_v2 import SmaMacdCrossV2Strategy
from src.strategies.sma_macd_cross_v3 import SmaMacdCrossV3Strategy
from src.strategies.sma_macd_cross_v4 import SmaMacdCrossV4Strategy
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
    elif strategy_name == "sma_macd_cross_v2":
        return SmaMacdCrossV2Strategy(parameters)
    elif strategy_name == "sma_macd_cross_v3":
        return SmaMacdCrossV3Strategy(parameters)
    elif strategy_name == "sma_macd_cross_v4":
        return SmaMacdCrossV4Strategy(parameters)
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


# ── Job store (in-memory) ─────────────────────────────────────────────────────
# job_id → {"status": "running"|"done"|"error", "progress": 0-100,
#            "message": str, "result": dict|None, "error": str|None}
import uuid
import asyncio as _asyncio
_jobs: dict = {}


# ── Pre-compute indicators for sma_macd_cross ────────────────────────────────

def _precompute_sma_macd(df, parameters):
    """
    Tính toàn bộ indicators 1 lần trên DataFrame đầy đủ.
    Trả về DataFrame với các cột indicator đã tính sẵn.
    Nhanh hơn ~100x so với tính lại mỗi nến.
    """
    import pandas as pd
    from src.data.indicators import add_custom_sma_to_df, add_custom_macd_to_df
    from src.strategies.sma_macd_cross import _slope_color, _find_signal_phase_start, SIG_BULLISH, SIG_BEARISH

    df = add_custom_sma_to_df(
        df,
        fast_len=parameters.get("fast_len", 1),
        slow_len=parameters.get("slow_len", 5),
        len_c=parameters.get("len_c", 200),
        factor=parameters.get("factor", 0.05),
        bb_length=parameters.get("bb_length", 50),
    )
    df = add_custom_macd_to_df(
        df,
        fast=parameters.get("macd_fast", 12),
        slow=parameters.get("macd_slow", 26),
        signal_length=parameters.get("macd_signal_length", 500),
        src=parameters.get("macd_src", "EMA"),
        sig_type=parameters.get("macd_sig_type", "EMA"),
    )

    # Pre-compute màu slope cho từng nến
    ma_arr   = df["custom_sma_basis"].to_numpy()
    sig_arr  = df["custom_macd_signal"].to_numpy()
    macd_arr = df["custom_macd"].to_numpy()
    n = len(df)

    ma_colors   = ["yellow"] * n
    sig_colors  = ["yellow"] * n
    macd_colors = ["yellow"] * n

    for i in range(2, n):
        ma_colors[i]   = _slope_color(ma_arr[i],   ma_arr[i-1],   ma_arr[i-2])
        sig_colors[i]  = _slope_color(sig_arr[i],  sig_arr[i-1],  sig_arr[i-2])
        macd_colors[i] = _slope_color(macd_arr[i], macd_arr[i-1], macd_arr[i-2])

    df["_ma_color"]   = ma_colors
    df["_sig_color"]  = sig_colors
    df["_macd_color"] = macd_colors

    # Pre-compute sig_phase_start_ts cho từng nến
    # Duyệt forward: khi sig_color đổi nhóm → phase mới bắt đầu
    phase_starts = [0] * n
    current_phase_start = 0
    current_phase_group = None  # "bullish" | "bearish" | None

    for i in range(n):
        sc = sig_colors[i]
        if sc in SIG_BULLISH:
            group = "bullish"
        elif sc in SIG_BEARISH:
            group = "bearish"
        else:
            group = None

        if group != current_phase_group:
            current_phase_group = group
            current_phase_start = i

        phase_starts[i] = current_phase_start

    df["_sig_phase_start_idx"] = phase_starts

    return df


def _simulate_sma_macd_candle(df, i, open_position, last_entry_phase, parameters):
    """
    Simulate 1 nến cho sma_macd_cross / sma_macd_cross_v2 dùng pre-computed indicators.
    Trả về signal dict: {"type": "long"|"short"|"close_long"|"close_short"|"none", "price": float, "metadata": dict}
    """
    from src.strategies.sma_macd_cross import SIG_BULLISH, SIG_BEARISH

    row = df.iloc[i]
    close_curr = float(row["close"])
    close_prev = float(df["close"].iloc[i-1])
    high_curr  = float(row["high"])
    low_curr   = float(row["low"])

    ma_curr  = float(row["custom_sma_basis"])
    ma_prev  = float(df["custom_sma_basis"].iloc[i-1])
    macd_curr = float(row["custom_macd"])
    sig_curr  = float(row["custom_macd_signal"])

    ma_color   = row["_ma_color"]
    sig_color  = row["_sig_color"]
    macd_color = row["_macd_color"]

    phase_start_idx = int(row["_sig_phase_start_idx"])
    sig_phase_start_ts = int(df["timestamp"].iloc[phase_start_idx])

    # Trend từ custom_sma (dùng cho V2 trend filter)
    trend_curr = int(row.get("custom_sma_trend", 0))
    use_trend_filter = parameters.get("use_trend_filter", False)  # V1: False, V2: True (set trong strategy)

    # V3 params
    min_ma_distance_pct = float(parameters.get("min_ma_distance_pct", 0.0))
    min_hold_candles    = int(parameters.get("min_hold_candles", 0))
    # V4 params
    stop_loss_pct   = float(parameters.get("stop_loss_pct", 0.0))
    take_profit_pct = float(parameters.get("take_profit_pct", 0.0))

    # Tính số nến đã giữ lệnh (cho V3 min_hold)
    candles_held = 0
    if open_position and min_hold_candles > 0:
        entry_candle_ts = int((open_position.get("metadata") or {}).get("entry_candle_ts", 0) or 0)
        if entry_candle_ts:
            ts_arr = [int(t) for t in df["timestamp"].tolist()]
            try:
                entry_idx = next(idx for idx, t in enumerate(ts_arr) if t >= entry_candle_ts)
                candles_held = i - entry_idx
            except StopIteration:
                candles_held = 0

    # ── EXIT ──────────────────────────────────────────────────────────────────
    if open_position:
        side = open_position["side"]
        pos_ma_cross = float((open_position.get("metadata") or {}).get("ma_cross_price", open_position["entry_price"]))
        pos_dev      = float((open_position.get("metadata") or {}).get("entry_deviation", 0))
        # V4: lay entry_price tu metadata (chinh xac hon)
        pos_ep = float((open_position.get("metadata") or {}).get("entry_price", 0) or open_position.get("entry_price", 0) or 0)

        if side == "long":
            # V4: chi SL/TP, bo TH1/TH2/TH3
            if stop_loss_pct > 0 and pos_ep > 0:
                sl = pos_ep * (1 - stop_loss_pct / 100)
                tp = pos_ep * (1 + take_profit_pct / 100) if take_profit_pct > 0 else None
                if close_curr <= sl:
                    return {"type": "close_long", "price": close_curr, "reason": f"SL {stop_loss_pct}%: close={close_curr:.4f}<=SL={sl:.4f}"}
                if tp and close_curr >= tp:
                    return {"type": "close_long", "price": close_curr, "reason": f"TP {take_profit_pct}%: close={close_curr:.4f}>=TP={tp:.4f}"}
                # V4: khong check TH1/TH2/TH3
                return {"type": "none", "price": close_curr}

            # V1/V2/V3: TH2/TH3/TH1
            if sig_color in SIG_BEARISH:
                return {"type": "close_long", "price": close_curr, "reason": f"TH2: Signal {sig_color}"}
            if macd_color == "red" and ma_color == "green":
                return {"type": "close_long", "price": close_curr, "reason": "TH3: MACD do + MA xanh la"}
            if close_curr < ma_curr:
                if candles_held >= min_hold_candles:
                    threshold = pos_ma_cross + pos_dev
                    if close_curr < threshold:
                        exit_price = (low_curr + ma_curr) / 2
                        return {"type": "close_long", "price": exit_price, "reason": f"TH1: close<MA hold={candles_held}"}

        elif side == "short":
            # V4: chi SL/TP, bo TH1/TH2/TH3
            if stop_loss_pct > 0 and pos_ep > 0:
                sl = pos_ep * (1 + stop_loss_pct / 100)
                tp = pos_ep * (1 - take_profit_pct / 100) if take_profit_pct > 0 else None
                if close_curr >= sl:
                    return {"type": "close_short", "price": close_curr, "reason": f"SL {stop_loss_pct}%: close={close_curr:.4f}>=SL={sl:.4f}"}
                if tp and close_curr <= tp:
                    return {"type": "close_short", "price": close_curr, "reason": f"TP {take_profit_pct}%: close={close_curr:.4f}<=TP={tp:.4f}"}
                # V4: khong check TH1/TH2/TH3
                return {"type": "none", "price": close_curr}

            # V1/V2/V3: TH2/TH3/TH1
            if sig_color in SIG_BULLISH:
                return {"type": "close_short", "price": close_curr, "reason": f"TH2: Signal {sig_color}"}
            if macd_color == "blue" and ma_color == "orange":
                return {"type": "close_short", "price": close_curr, "reason": "TH3: MACD xanh + MA cam"}
            if close_curr > ma_curr:
                if candles_held >= min_hold_candles:
                    threshold = pos_ma_cross + pos_dev
                    if close_curr > threshold:
                        exit_price = (high_curr + ma_curr) / 2
                        return {"type": "close_short", "price": exit_price, "reason": f"TH1: close>MA hold={candles_held}"}

        return {"type": "none", "price": close_curr}

    # ── ENTRY ─────────────────────────────────────────────────────────────────
    # Khoang cach gia-MA (V3)
    ma_dist_pct = abs(close_curr - ma_curr) / ma_curr * 100 if ma_curr else 0

    # LONG
    cond1_long = sig_color in SIG_BULLISH
    cond2_long = macd_curr >= sig_curr
    cond3_long = (close_prev <= ma_prev) and (close_curr > ma_curr)
    cond4_long = (not use_trend_filter) or (trend_curr == 1)
    cond5_long = ma_dist_pct >= min_ma_distance_pct  # V3: khoang cach toi thieu

    if cond1_long and cond2_long and cond3_long and cond4_long and cond5_long:
        # One-shot check
        if "long" in last_entry_phase and last_entry_phase["long"] == sig_phase_start_ts:
            return {"type": "none", "price": close_curr}
        ma_cross = ma_curr
        entry_price = (high_curr + ma_cross) / 2
        deviation = abs(entry_price - ma_cross)
        curr_ts = int(df["timestamp"].iloc[i])
        return {
            "type": "long", "price": entry_price,
            "metadata": {
                "ma_cross_price": round(ma_cross, 6),
                "entry_deviation": round(deviation, 6),
                "entry_candle_ts": curr_ts,
                "sig_phase_start_ts": sig_phase_start_ts,
                "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                "ma": round(ma_curr, 6), "close": round(close_curr, 6),
            }
        }

    # SHORT
    cond1_short = sig_color in SIG_BEARISH
    cond2_short = macd_curr <= sig_curr
    cond3_short = (close_prev >= ma_prev) and (close_curr < ma_curr)
    cond4_short = (not use_trend_filter) or (trend_curr == -1)
    cond5_short = ma_dist_pct >= min_ma_distance_pct  # V3: khoang cach toi thieu

    if cond1_short and cond2_short and cond3_short and cond4_short and cond5_short:
        # One-shot check
        if "short" in last_entry_phase and last_entry_phase["short"] == sig_phase_start_ts:
            return {"type": "none", "price": close_curr}
        ma_cross = ma_curr
        entry_price = (low_curr + ma_cross) / 2
        deviation = abs(entry_price - ma_cross)
        curr_ts = int(df["timestamp"].iloc[i])
        return {
            "type": "short", "price": entry_price,
            "metadata": {
                "ma_cross_price": round(ma_cross, 6),
                "entry_deviation": round(deviation, 6),
                "entry_candle_ts": curr_ts,
                "sig_phase_start_ts": sig_phase_start_ts,
                "ma_color": ma_color, "sig_color": sig_color, "macd_color": macd_color,
                "ma": round(ma_curr, 6), "close": round(close_curr, 6),
            }
        }

    return {"type": "none", "price": close_curr}


async def _run_backtest_engine(bot, exchange, start_ms, end_ms, initial_balance,
                                timeframe_override=None, job_id=None):
    """
    Backtest engine với pre-computed indicators (nhanh hơn ~100x).
    Cập nhật progress vào _jobs[job_id] nếu có.
    """
    import pandas as pd

    def _update_progress(pct, msg):
        if job_id and job_id in _jobs:
            _jobs[job_id]["progress"] = pct
            _jobs[job_id]["message"] = msg

    strategy_name = bot.strategy_name
    parameters = bot.parameters or {}
    timeframe = timeframe_override or parameters.get("timeframe", "5m")
    leverage = int(parameters.get("leverage", 5))
    position_size_pct = float(parameters.get("position_size_pct", 0.10))
    lookback = _get_lookback(strategy_name, parameters)

    symbols_raw = bot.symbols or ["BTCUSDT"]
    symbol = _normalize_symbol(symbols_raw[0] if symbols_raw else "BTCUSDT")
    tf_ms = _timeframe_ms(timeframe)

    _update_progress(5, f"Đang tải dữ liệu {symbol} {timeframe}...")
    logger.info(f"Backtest [{job_id}]: fetch {symbol} {timeframe} {start_ms}→{end_ms}")

    warmup_start_ms = start_ms - (lookback * tf_ms * 2)
    all_candles = await _fetch_ohlcv_range(exchange, symbol, timeframe, warmup_start_ms, end_ms)

    if len(all_candles) < lookback + 10:
        raise ValueError(
            f"Không đủ dữ liệu: có {len(all_candles)} nến, cần ít nhất {lookback + 10}."
        )

    total_candles = len(all_candles)
    logger.info(f"Backtest [{job_id}]: {total_candles} candles fetched")
    _update_progress(15, f"Đã tải {total_candles} nến. Đang tính indicators...")

    # ── Pre-compute indicators (1 lần cho toàn bộ) ───────────────────────────
    df = pd.DataFrame(all_candles, columns=["timestamp","open","high","low","close","volume"])

    if strategy_name == "sma_macd_cross":
        df = _precompute_sma_macd(df, parameters)
    elif strategy_name in ("sma_macd_cross_v2", "sma_macd_cross_v3", "sma_macd_cross_v4"):
        df = _precompute_sma_macd(df, parameters)
    else:
        # Fallback: dùng strategy.analyze() cho các chiến lược khác
        # (chậm hơn nhưng đúng)
        pass

    _update_progress(25, "Đang simulate giao dịch...")

    # ── Tìm start_idx ─────────────────────────────────────────────────────────
    start_idx = lookback
    for i, c in enumerate(all_candles):
        if c[0] >= start_ms and i >= lookback:
            start_idx = i
            break
    if start_idx < lookback:
        start_idx = lookback

    # ── Simulation loop ───────────────────────────────────────────────────────
    balance = initial_balance
    open_position = None
    trades = []
    equity_curve = [{"ts": all_candles[start_idx][0], "balance": balance, "pnl_cum": 0.0, "drawdown_pct": 0.0}]
    peak_balance = balance
    last_entry_phase: dict = {}

    simulate_range = [i for i in range(start_idx, len(all_candles)) if all_candles[i][0] <= end_ms]
    total_sim = len(simulate_range)

    for loop_idx, i in enumerate(simulate_range):
        candle = all_candles[i]
        ts_ms = candle[0]

        # Progress update mỗi 5%
        if total_sim > 0 and loop_idx % max(1, total_sim // 20) == 0:
            pct = 25 + int(loop_idx / total_sim * 65)
            _update_progress(pct, f"Simulate nến {loop_idx+1}/{total_sim}...")

        # ── Lấy signal ────────────────────────────────────────────────────────
        if strategy_name in ("sma_macd_cross", "sma_macd_cross_v2", "sma_macd_cross_v3", "sma_macd_cross_v4") and i >= 2:
            sig = _simulate_sma_macd_candle(df, i, open_position, last_entry_phase, parameters)
        else:
            # Fallback: gọi strategy.analyze() (chậm)
            ohlcv_slice = all_candles[max(0, i - lookback * 2): i + 1]
            sim_pos = []
            if open_position:
                sim_pos = [{"symbol": symbol, "side": open_position["side"],
                            "size": open_position["size"], "entry_price": open_position["entry_price"],
                            "metadata": open_position.get("metadata", {})}]
            try:
                strategy = _build_strategy(strategy_name, parameters)
                signal_obj = await strategy.analyze(symbol, ohlcv_slice, sim_pos)
                sig_type = signal_obj.signal if not signal_obj.is_none else "none"
                sig = {"type": sig_type, "price": signal_obj.price, "metadata": signal_obj.metadata or {}}
            except Exception as e:
                logger.warning(f"Strategy error at candle {i}: {e}")
                continue

        sig_type = sig.get("type", "none")

        # ── Entry ─────────────────────────────────────────────────────────────
        if sig_type in ("long", "short") and open_position is None:
            entry_price = sig.get("price") or candle[4]
            if not entry_price or entry_price <= 0:
                entry_price = candle[4]
            # V4: dung notional_usdt co dinh thay vi % balance
            notional_usdt = float(parameters.get("notional_usdt", 0))
            if notional_usdt > 0:
                position_value = notional_usdt
            else:
                position_value = balance * position_size_pct * leverage
            size = position_value / entry_price
            fee = position_value * COMMISSION
            open_position = {
                "side": sig_type, "entry_price": entry_price, "size": size,
                "position_value": position_value, "entry_fee": fee,
                "entry_ts": ts_ms, "entry_candle_idx": i,
                "metadata": sig.get("metadata") or {},
            }
            balance -= fee
            # One-shot tracking
            phase_ts = (sig.get("metadata") or {}).get("sig_phase_start_ts")
            if phase_ts:
                last_entry_phase[sig_type] = phase_ts

        # ── Exit ──────────────────────────────────────────────────────────────
        elif sig_type in ("close_long", "close_short") and open_position is not None:
            exit_price = sig.get("price") or candle[4]
            if not exit_price or exit_price <= 0:
                exit_price = candle[4]
            pos = open_position
            pv = pos["position_value"]
            if pos["side"] == "long":
                price_change_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
            else:
                price_change_pct = (pos["entry_price"] - exit_price) / pos["entry_price"]
            gross_pnl = pv * price_change_pct
            exit_fee = pv * COMMISSION
            net_pnl = gross_pnl - pos["entry_fee"] - exit_fee
            pnl_pct = net_pnl / (pv / leverage) * 100
            balance += net_pnl
            holding_candles = i - pos["entry_candle_idx"]
            trades.append({
                "entry_time": _to_utc7_str(pos["entry_ts"]),
                "exit_time":  _to_utc7_str(ts_ms),
                "entry_ts_ms": pos["entry_ts"],
                "exit_ts_ms":  ts_ms,
                "symbol": symbol, "side": pos["side"],
                "entry_price": pos["entry_price"], "exit_price": exit_price,
                "size": pos["size"],
                "pnl": round(net_pnl, 4), "pnl_pct": round(pnl_pct, 2),
                "balance_after": round(balance, 4),
                "holding_candles": holding_candles,
            })
            pnl_cum = balance - initial_balance
            peak_balance = max(peak_balance, balance)
            drawdown_pct = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0.0
            equity_curve.append({"ts": ts_ms, "balance": round(balance, 4),
                                  "pnl_cum": round(pnl_cum, 4), "drawdown_pct": round(drawdown_pct, 2)})
            open_position = None

    _update_progress(92, "Đang tính thống kê...")

    # ── Summary stats ─────────────────────────────────────────────────────────
    total_trades = len(trades)
    winning = [t for t in trades if t["pnl"] > 0]
    losing  = [t for t in trades if t["pnl"] <= 0]
    win_count  = len(winning)
    loss_count = len(losing)
    win_rate = round(win_count / total_trades * 100, 2) if total_trades > 0 else 0.0
    total_pnl = sum(t["pnl"] for t in trades)
    total_return_pct = round((balance - initial_balance) / initial_balance * 100, 2)
    gross_profit = sum(t["pnl"] for t in winning)
    gross_loss   = abs(sum(t["pnl"] for t in losing))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else 999.0
    avg_win  = round(gross_profit / win_count, 4)  if win_count  > 0 else 0.0
    avg_loss = round(-gross_loss / loss_count, 4)  if loss_count > 0 else 0.0
    largest_win  = round(max((t["pnl"] for t in winning), default=0.0), 4)
    largest_loss = round(min((t["pnl"] for t in losing),  default=0.0), 4)
    avg_holding  = round(sum(t["holding_candles"] for t in trades) / total_trades, 1) if total_trades > 0 else 0.0
    peak = initial_balance
    max_dd = 0.0
    for t in trades:
        peak = max(peak, t["balance_after"])
        dd = (peak - t["balance_after"]) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    max_drawdown_pct = round(max_dd, 2)
    if len(trades) > 1:
        returns = [t["pnl_pct"] / 100 for t in trades]
        mean_r = sum(returns) / len(returns)
        std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns))
        tf_per_day = 86400_000 / tf_ms
        annual_factor = math.sqrt(tf_per_day * 252)
        sharpe = round((mean_r / std_r * annual_factor) if std_r > 0 else 0.0, 3)
    else:
        sharpe = 0.0

    summary = {
        "total_trades": total_trades, "winning_trades": win_count, "losing_trades": loss_count,
        "win_rate": win_rate, "total_pnl": round(total_pnl, 4), "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct, "profit_factor": profit_factor,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "largest_win": largest_win, "largest_loss": largest_loss,
        "avg_holding_candles": avg_holding, "sharpe_ratio": sharpe,
        "initial_balance": initial_balance, "final_balance": round(balance, 4),
    }
    return {"symbol": symbol, "timeframe": timeframe, "trades": trades,
            "equity_curve": equity_curve, "summary": summary}


# ── Excel export ─────────────────────────────────────────────────────────────

def _create_excel(bot, result, start_date, end_date, filepath):
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError("openpyxl is required. Run: pip install openpyxl>=3.1.2")

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    wb = openpyxl.Workbook()
    green_fill  = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_fill    = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    alt_fill    = PatternFill(start_color="DEEAF1", end_color="DEEAF1", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    bold_font   = Font(bold=True)

    summary      = result["summary"]
    trades       = result["trades"]
    equity_curve = result["equity_curve"]
    symbol       = result["symbol"]
    timeframe    = result["timeframe"]

    # ── Sheet 1: Tổng hợp ────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Tong hop"
    ws1.column_dimensions["A"].width = 32
    ws1.column_dimensions["B"].width = 25

    info_rows = [
        ("THONG TIN BOT", ""),
        ("Ten bot",                  bot.name),
        ("Chien luoc",               bot.strategy_name),
        ("Symbol",                   symbol),
        ("Timeframe",                timeframe),
        ("Tu ngay",                  start_date),
        ("Den ngay",                 end_date),
        ("Von ban dau (USDT)",       summary["initial_balance"]),
        ("", ""),
        ("KET QUA BACKTEST", ""),
        ("Tong so lenh",             summary["total_trades"]),
        ("Lenh thang",               summary["winning_trades"]),
        ("Lenh thua",                summary["losing_trades"]),
        ("Ti le thang (%)",          summary["win_rate"]),
        ("Tong Pnl (USDT)",          summary["total_pnl"]),
        ("Tong loi nhuan (%)",       summary["total_return_pct"]),
        ("Von cuoi (USDT)",          summary["final_balance"]),
        ("Max Drawdown (%)",         summary["max_drawdown_pct"]),
        ("Profit Factor",            summary["profit_factor"]),
        ("TB lenh thang (USDT)",     summary["avg_win"]),
        ("TB lenh thua (USDT)",      summary["avg_loss"]),
        ("Lenh thang lon nhat",      summary["largest_win"]),
        ("Lenh thua lon nhat",       summary["largest_loss"]),
        ("TB thoi gian giu (nen)",   summary["avg_holding_candles"]),
        ("Sharpe Ratio",             summary["sharpe_ratio"]),
    ]

    pos_labels = {"Tong Pnl (USDT)", "Tong loi nhuan (%)", "Von cuoi (USDT)",
                  "Profit Factor", "Sharpe Ratio", "TB lenh thang (USDT)", "Lenh thang lon nhat"}
    neg_labels = {"Max Drawdown (%)", "TB lenh thua (USDT)", "Lenh thua lon nhat"}

    for row_idx, (label, value) in enumerate(info_rows, start=1):
        cell_a = ws1.cell(row=row_idx, column=1, value=label)
        cell_b = ws1.cell(row=row_idx, column=2, value=value)
        if label in ("THONG TIN BOT", "KET QUA BACKTEST"):
            cell_a.font = header_font; cell_a.fill = header_fill
            cell_b.fill = header_fill
        elif label:
            cell_a.font = bold_font
            if isinstance(value, (int, float)):
                if label in pos_labels:
                    cell_b.fill = green_fill if value >= 0 else red_fill
                elif label in neg_labels:
                    cell_b.fill = red_fill if value != 0 else green_fill

    # ── Sheet 2: Chi tiết lệnh ────────────────────────────────────────────────
    ws2 = wb.create_sheet("Chi tiet lenh")
    headers2   = ["#", "Thoi gian vao", "Thoi gian ra", "Symbol", "Side",
                  "Gia vao", "Gia ra", "So luong", "Pnl (USDT)", "Pnl (%)",
                  "So du sau lenh", "Thoi gian giu (nen)"]
    col_widths2 = [5, 18, 18, 12, 8, 14, 14, 12, 14, 10, 16, 18]
    for col_idx, (h, w) in enumerate(zip(headers2, col_widths2), start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws2.column_dimensions[get_column_letter(col_idx)].width = w

    for t_idx, trade in enumerate(trades, start=1):
        row      = t_idx + 1
        fill     = alt_fill if t_idx % 2 == 0 else None
        pnl_fill = green_fill if trade["pnl"] > 0 else red_fill
        values   = [t_idx, trade["entry_time"], trade["exit_time"], trade["symbol"],
                    trade["side"].upper(), trade["entry_price"], trade["exit_price"],
                    round(trade["size"], 4), trade["pnl"], trade["pnl_pct"],
                    trade["balance_after"], trade["holding_candles"]]
        for col_idx, val in enumerate(values, start=1):
            cell = ws2.cell(row=row, column=col_idx, value=val)
            if col_idx in (9, 10):
                cell.fill = pnl_fill
            elif fill:
                cell.fill = fill

    # ── Sheet 3: Đường vốn ───────────────────────────────────────────────────
    ws3 = wb.create_sheet("Duong von")
    headers3    = ["Thoi gian", "So du", "Pnl tich luy", "Drawdown (%)"]
    col_widths3 = [18, 16, 16, 14]
    for col_idx, (h, w) in enumerate(zip(headers3, col_widths3), start=1):
        cell = ws3.cell(row=1, column=col_idx, value=h)
        cell.font = header_font; cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws3.column_dimensions[get_column_letter(col_idx)].width = w

    for eq_idx, eq in enumerate(equity_curve, start=1):
        row      = eq_idx + 1
        fill     = alt_fill if eq_idx % 2 == 0 else None
        pnl_fill = green_fill if eq["pnl_cum"] >= 0 else red_fill
        dd_fill  = red_fill if eq["drawdown_pct"] > 5 else (alt_fill if eq["drawdown_pct"] > 0 else None)
        for col_idx, (val, f) in enumerate(
            [(_to_utc7_str(eq["ts"]), fill), (eq["balance"], fill),
             (eq["pnl_cum"], pnl_fill), (eq["drawdown_pct"], dd_fill)],
            start=1
        ):
            cell = ws3.cell(row=row, column=col_idx, value=val)
            if f:
                cell.fill = f

    wb.save(filepath)
    logger.info(f"Excel saved: {filepath}")


# ── Background job runner ─────────────────────────────────────────────────────

async def _run_job(job_id: str, bot, account, req):
    """Chạy backtest trong background, cập nhật _jobs[job_id]."""
    parameters = bot.parameters or {}
    market_type = parameters.get("market_type", "futures")

    if account:
        exchange = BinanceExchange(
            api_key=account.api_key, api_secret=account.api_secret,
            mode=account.mode, market_type=market_type,
        )
    else:
        exchange = create_exchange_from_env()
        exchange.market_type = market_type

    try:
        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ms = int(start_dt.timestamp() * 1000)
        if req.end_date:
            end_dt = datetime.strptime(req.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = datetime.now(timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000)
        end_date_str = end_dt.strftime("%Y-%m-%d")

        # Validate: start phải trước end
        if start_ms >= end_ms:
            raise ValueError(
                f"Ngày bắt đầu ({req.start_date}) phải trước ngày kết thúc ({end_date_str}). "
                f"Kiểm tra lại khoảng thời gian."
            )

        # Retry connect toi da 3 lan neu timeout
        connect_ok = False
        last_connect_err = None
        for attempt in range(1, 4):
            try:
                _jobs[job_id]["message"] = f"Đang kết nối exchange (lần {attempt}/3)..."
                await exchange.connect()
                connect_ok = True
                break
            except Exception as e_conn:
                last_connect_err = e_conn
                logger.warning(f"Backtest [{job_id}]: connect attempt {attempt} failed: {e_conn}")
                if attempt < 3:
                    await _asyncio.sleep(3)
                    # Tao lai exchange object de reset connection state
                    if account:
                        exchange = BinanceExchange(
                            api_key=account.api_key, api_secret=account.api_secret,
                            mode=account.mode, market_type=market_type,
                        )
                    else:
                        exchange = create_exchange_from_env()
                        exchange.market_type = market_type

        if not connect_ok:
            raise ValueError(
                f"Không thể kết nối exchange sau 3 lần thử. "
                f"Lỗi: {type(last_connect_err).__name__}: {last_connect_err}. "
                f"Vui lòng thử lại sau."
            )

        result = await _run_backtest_engine(
            bot=bot, exchange=exchange,
            start_ms=start_ms, end_ms=end_ms,
            initial_balance=req.initial_balance,
            timeframe_override=req.timeframe or None,
            job_id=job_id,
        )
        await exchange.close()

        _jobs[job_id]["message"] = "Đang xuất Excel..."
        _jobs[job_id]["progress"] = 95

        symbol_safe = result["symbol"].replace("/", "")
        tf_safe     = result["timeframe"]
        start_safe  = req.start_date.replace("-", "")
        end_safe    = end_date_str.replace("-", "")
        filename = f"backtest_{req.bot_id}_{symbol_safe}_{tf_safe}_{start_safe}_{end_safe}.xlsx"
        filepath = os.path.join(BACKTEST_DIR, filename)
        _create_excel(bot=bot, result=result, start_date=req.start_date,
                      end_date=end_date_str, filepath=filepath)

        _jobs[job_id].update({
            "status": "done",
            "progress": 100,
            "message": f"Hoàn tất — {result['summary']['total_trades']} lệnh",
            "result": {
                "success": True,
                "bot_id": req.bot_id, "bot_name": bot.name,
                "symbol": result["symbol"], "timeframe": result["timeframe"],
                "start_date": req.start_date, "end_date": end_date_str,
                "initial_balance": req.initial_balance,
                "summary": result["summary"],
                "trades": result["trades"],
                "equity_curve": result["equity_curve"],
                "excel_filename": filename,
                "download_url": f"/api/backtest/download/{filename}",
            },
        })
        logger.info(f"Backtest job {job_id} done: {result['summary']['total_trades']} trades")

    except Exception as e:
        try:
            await exchange.close()
        except Exception:
            pass
        logger.exception(f"Backtest job {job_id} error: {e}")
        _jobs[job_id].update({
            "status": "error",
            "progress": 0,
            "message": f"Lỗi: {type(e).__name__}: {str(e)}",
            "error": str(e),
        })


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_backtest(req: BacktestRequest):
    """Khởi động backtest dưới dạng background job. Trả về job_id để poll progress."""

    # Validate ngày trước khi tạo job
    try:
        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"start_date không hợp lệ: {req.start_date}")

    if req.end_date:
        try:
            end_dt = datetime.strptime(req.end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"end_date không hợp lệ: {req.end_date}")
        if start_dt >= end_dt:
            raise HTTPException(
                status_code=400,
                detail=f"Ngày bắt đầu ({req.start_date}) phải trước ngày kết thúc ({req.end_date})."
            )

    if req.initial_balance <= 0:
        raise HTTPException(status_code=400, detail="Vốn ban đầu phải > 0")

    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == req.bot_id, Bot.is_deleted == False))
        bot = result.scalar_one_or_none()
        if not bot:
            raise HTTPException(status_code=404, detail=f"Bot ID={req.bot_id} not found")
        account = None
        if bot.account_id:
            acc_result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.id == bot.account_id))
            account = acc_result.scalar_one_or_none()

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "message": "Đang khởi động...",
        "result": None,
        "error": None,
    }

    # Chạy background — không block HTTP response
    _asyncio.create_task(_run_job(job_id, bot, account, req))

    return {"job_id": job_id, "status": "running"}


@router.get("/progress/{job_id}")
async def get_progress(job_id: str):
    """Poll tiến độ backtest. UI gọi mỗi 2s."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {
        "job_id": job_id,
        "status": job["status"],       # "running" | "done" | "error"
        "progress": job["progress"],   # 0-100
        "message": job["message"],
        "result": job["result"],       # None khi đang chạy, dict khi done
        "error": job["error"],
    }


@router.get("/download/{filename}")
async def download_backtest(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(BACKTEST_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return FileResponse(
        path=filepath, filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


