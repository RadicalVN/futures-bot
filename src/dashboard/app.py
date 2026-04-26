import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import asyncio
import json
from datetime import datetime

from src.database.db import init_db, get_db
from src.database.models import Trade, Signal, Bot, ExchangeAccount, BotEvent
from sqlalchemy import select, desc, func, update

bot_manager = None

def set_bot_manager(manager):
    global bot_manager
    bot_manager = manager


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.remove(conn)

ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Dashboard đang khởi động...")
    await init_db()
    yield
    logger.info("Dashboard đang tắt...")


app = FastAPI(
    title="Binance Bot Management Platform",
    description="Quản lý và theo dõi nhiều bot giao dịch",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(os.path.join(static_dir, "index.html"))


# --- API Accounts ---
@app.get("/api/accounts")
async def get_accounts():
    async with get_db() as db:
        result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.is_active == True))
        return [acc.to_dict() for acc in result.scalars().all()]

@app.post("/api/accounts")
async def create_account(req: Request):
    data = await req.json()
    async with get_db() as db:
        acc = ExchangeAccount(
            name=data.get("name"),
            api_key=data.get("api_key"),
            api_secret=data.get("api_secret"),
            mode=data.get("mode", "testnet")
        )
        db.add(acc)
        await db.commit()
        return {"success": True, "id": acc.id}


# --- API Bots ---
@app.get("/api/bots")
async def get_bots():
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.is_deleted == False))
        return [b.to_dict() for b in result.scalars().all()]

@app.post("/api/bots")
async def create_bot(req: Request):
    data = await req.json()
    async with get_db() as db:
        bot = Bot(
            name=data.get("name"),
            account_id=data.get("account_id"),
            symbols=data.get("symbols", ["BTCUSDT"]),
            strategy_name=data.get("strategy_name", "ma_macd"),
            parameters=data.get("parameters", {}),
            status="stopped"
        )
        db.add(bot)
        await db.commit()
        return {"success": True, "id": bot.id}

@app.put("/api/bots/{bot_id}/status")
async def update_bot_status(bot_id: int, req: Request):
    data = await req.json()
    status = data.get("status")
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.is_deleted == False))
        bot = result.scalar_one_or_none()
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        bot.status = status
        await db.commit()
        return {"success": True, "status": bot.status}

@app.delete("/api/bots/{bot_id}")
async def delete_bot(bot_id: int):
    async with get_db() as db:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot:
            bot.is_deleted = True
            bot.status = "stopped"
            await db.commit()
        return {"success": True}


# --- API Logs & Data ---
@app.get("/api/events")
async def get_events(limit: int = 50):
    async with get_db() as db:
        result = await db.execute(select(BotEvent).order_by(desc(BotEvent.timestamp)).limit(limit))
        return [e.to_dict() for e in result.scalars().all()]

@app.get("/api/trades")
async def get_trades(limit: int = 50, bot_id: int = None):
    async with get_db() as db:
        q = select(Trade)
        if bot_id:
            q = q.where(Trade.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Trade.created_at)).limit(limit))
        return [t.to_dict() for t in result.scalars().all()]

@app.get("/api/signals")
async def get_signals(limit: int = 50, bot_id: int = None):
    async with get_db() as db:
        q = select(Signal)
        if bot_id:
            q = q.where(Signal.bot_id == bot_id)
        result = await db.execute(q.order_by(desc(Signal.timestamp)).limit(limit))
        return [s.to_dict() for s in result.scalars().all()]



# --- Market Data API ---
@app.get("/api/symbols")
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
                # Dùng id gốc của Binance (vd: BTCUSDT) thay vì format của CCXT (BTC/USDT:USDT)
                symbols.append(market.get('id', '').upper())
        
        # Loại bỏ rỗng và sort
        symbols = sorted(list(set(filter(bool, symbols))))
        return {"symbols": symbols}
    except Exception as e:
        logger.error(f"Lỗi lấy danh sách symbols: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/chart-data/{symbol:path}")
async def get_chart_data(symbol: str, timeframe: str = "15m", limit: int = 100):
    from src.core.exchange import create_exchange_from_env
    exchange = create_exchange_from_env()
    try:
        await exchange.connect()
        ohlcv = await exchange.fetch_ohlcv(symbol.replace("-", "/"), timeframe, limit)
        await exchange.close()
        
        formatted_data = []
        for row in ohlcv:
            formatted_data.append({
                "x": row[0],
                "o": row[1],
                "h": row[2],
                "l": row[3],
                "c": row[4],
            })
        return {"symbol": symbol, "data": formatted_data}
    except Exception as e:
        logger.error(f"Lỗi lấy chart data: {e}")
        raise HTTPException(500, str(e))


# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
