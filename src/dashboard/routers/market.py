from fastapi import APIRouter, HTTPException
import os
import pandas as pd
from loguru import logger

router = APIRouter(prefix="/api", tags=["Market Data"])

# Cache symbols để tránh gọi API liên tục
_symbols_cache: list = []
_symbols_cache_ts: float = 0


@router.get("/symbols")
async def get_symbols():
    import ccxt.async_support as ccxt
    import time

    global _symbols_cache, _symbols_cache_ts
    # Cache 10 phút
    if _symbols_cache and (time.time() - _symbols_cache_ts) < 600:
        return {"symbols": _symbols_cache}

    exchange = ccxt.binanceusdm({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    try:
        markets = await exchange.load_markets()
        await exchange.close()

        symbols = []
        for symbol, market in markets.items():
            if market.get('active') and market.get('quote') == 'USDT' and market.get('contract'):
                symbols.append(market.get('id', '').upper())

        symbols = sorted(list(set(filter(bool, symbols))))
        _symbols_cache = symbols
        _symbols_cache_ts = time.time()
        return {"symbols": symbols}
    except Exception as e:
        logger.error(f"Lỗi lấy danh sách symbols: {e}")
        # Trả về cache cũ nếu có, tránh crash UI
        if _symbols_cache:
            return {"symbols": _symbols_cache}
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chart-data/{symbol:path}")
async def get_chart_data(symbol: str, timeframe: str = "15m", limit: int = 1000, endTime: int = None):
    import ccxt.async_support as ccxt
    exchange = ccxt.binanceusdm({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    try:
        await exchange.load_markets()
        params = {}
        if endTime:
            params['endTime'] = endTime
        ohlcv = await exchange.fetch_ohlcv(symbol.replace("-", "/"), timeframe, limit=limit, params=params)
        await exchange.close()

        formatted_data = []
        from src.data.indicators import ohlcv_to_dataframe, add_custom_sma_to_df, add_custom_macd_to_df, add_adx_to_df
        df = ohlcv_to_dataframe(ohlcv)
        df = add_custom_sma_to_df(df)
        df = add_custom_macd_to_df(df)
        df = add_adx_to_df(df, period=int(float(os.environ.get("ADX_PERIOD", 14))))

        # Nan to None for JSON
        df = df.where(pd.notnull(df), None)

        for idx, row in df.iterrows():
            formatted_data.append({
                "x": int(idx.timestamp() * 1000),
                "o": row['open'],
                "h": row['high'],
                "l": row['low'],
                "c": row['close'],
                "sma_up": None if pd.isna(row.get('custom_sma_up')) else row['custom_sma_up'],
                "sma_dn": None if pd.isna(row.get('custom_sma_dn')) else row['custom_sma_dn'],
                "sma_trend": None if pd.isna(row.get('custom_sma_trend')) else row['custom_sma_trend'],
                "sma_basis": None if pd.isna(row.get('custom_sma_basis')) else row['custom_sma_basis'],
                "sma_momentum": None if pd.isna(row.get('custom_sma_momentum')) else row['custom_sma_momentum'],
                "sma_slope_pct": None if pd.isna(row.get('custom_sma_slope_pct')) else row['custom_sma_slope_pct'],
                "sma_momentum_pct": None if pd.isna(row.get('custom_sma_momentum_pct')) else row['custom_sma_momentum_pct'],
                "sma_momentum_n": row.get('custom_sma_momentum_n') or 'yellow',
                "sma_momentum_n_pct": None if pd.isna(row.get('custom_sma_momentum_n_pct')) else row['custom_sma_momentum_n_pct'],
                "macd": None if pd.isna(row.get('custom_macd')) else row['custom_macd'],
                "macd_signal": None if pd.isna(row.get('custom_macd_signal')) else row['custom_macd_signal'],
                "macd_hist": None if pd.isna(row.get('custom_macd_hist')) else row['custom_macd_hist'],
                "macd_hist_color": row.get('custom_macd_hist_color') or 'above_grow',
                "macd_momentum": row.get('custom_macd_momentum') or 'yellow',
                "macd_sig_momentum": row.get('custom_macd_sig_momentum') or 'yellow',
                "macd_slope_pct": None if pd.isna(row.get('custom_macd_slope_pct')) else row['custom_macd_slope_pct'],
                "macd_sig_slope_pct": None if pd.isna(row.get('custom_macd_sig_slope_pct')) else row['custom_macd_sig_slope_pct'],
                "macd_momentum_pct": None if pd.isna(row.get('custom_macd_momentum_pct')) else row['custom_macd_momentum_pct'],
                "macd_sig_momentum_pct": None if pd.isna(row.get('custom_macd_sig_momentum_pct')) else row['custom_macd_sig_momentum_pct'],
                "adx":          None if pd.isna(row.get('adx')) else row['adx'],
                "adx_plus_di":  None if pd.isna(row.get('adx_plus_di')) else row['adx_plus_di'],
                "adx_minus_di": None if pd.isna(row.get('adx_minus_di')) else row['adx_minus_di'],
            })
        return {"symbol": symbol, "data": formatted_data,
                "adx_threshold": float(os.environ.get("ADX_ENTRY_THRESHOLD", 25.0))}
    except Exception as e:
        logger.error(f"Lỗi lấy chart data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
