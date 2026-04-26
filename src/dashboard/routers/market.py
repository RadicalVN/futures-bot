from fastapi import APIRouter, HTTPException
import pandas as pd
from loguru import logger

router = APIRouter(prefix="/api", tags=["Market Data"])

@router.get("/symbols")
async def get_symbols():
    from src.core.exchange import create_exchange_from_env
    exchange = create_exchange_from_env()
    try:
        await exchange.connect()
        markets = exchange._exchange.markets
        await exchange.close()
        
        symbols = []
        for symbol, market in markets.items():
            if market.get('active') and market.get('quote') == 'USDT' and market.get('contract'):
                symbols.append(market.get('id', '').upper())
        
        symbols = sorted(list(set(filter(bool, symbols))))
        return {"symbols": symbols}
    except Exception as e:
        logger.error(f"Lỗi lấy danh sách symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chart-data/{symbol:path}")
async def get_chart_data(symbol: str, timeframe: str = "15m", limit: int = 1000):
    from src.core.exchange import create_exchange_from_env
    exchange = create_exchange_from_env()
    try:
        await exchange.connect()
        ohlcv = await exchange.fetch_ohlcv(symbol.replace("-", "/"), timeframe, limit)
        await exchange.close()
        
        formatted_data = []
        from src.data.indicators import ohlcv_to_dataframe, add_custom_sma_to_df, add_custom_macd_to_df
        df = ohlcv_to_dataframe(ohlcv)
        df = add_custom_sma_to_df(df)
        df = add_custom_macd_to_df(df)
        
        # Nan to None for JSON
        df = df.where(pd.notnull(df), None)

        for idx, row in df.iterrows():
            formatted_data.append({
                "x": int(idx.timestamp() * 1000),
                "o": row['open'],
                "h": row['high'],
                "l": row['low'],
                "c": row['close'],
                "sma_up": row['custom_sma_up'],
                "sma_dn": row['custom_sma_dn'],
                "sma_trend": row['custom_sma_trend'],
                "macd": row['custom_macd'],
                "macd_signal": row['custom_macd_signal']
            })
        return {"symbol": symbol, "data": formatted_data}
    except Exception as e:
        logger.error(f"Lỗi lấy chart data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
