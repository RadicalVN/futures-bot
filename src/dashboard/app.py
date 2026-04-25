"""
app.py — FastAPI Web Dashboard
Cung cấp REST API và serve frontend HTML
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import asyncio
import json
from datetime import datetime

from src.database.db import init_db, get_db
from src.database.models import Trade, Signal, BotStatus
from sqlalchemy import select, desc, func

# ─── Shared bot state (sẽ được set từ main.py) ───────────────────────────────
bot_engine = None  # Reference đến BotEngine instance


def set_bot_engine(engine):
    global bot_engine
    bot_engine = engine


# ─── WebSocket Connection Manager ────────────────────────────────────────────
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


# ─── App Lifecycle ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Dashboard đang khởi động...")
    await init_db()
    yield
    logger.info("Dashboard đang tắt...")


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Binance Trading Bot Dashboard",
    description="Quản lý và theo dõi Binance Futures Trading Bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ─── Frontend ────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """Serve trang dashboard chính"""
    return FileResponse(os.path.join(static_dir, "index.html"))


# ─── Bot Control API ─────────────────────────────────────────────────────────
@app.post("/api/bot/start")
async def start_bot():
    """Khởi động bot"""
    global bot_engine
    if bot_engine is None:
        raise HTTPException(status_code=503, detail="Bot engine chưa được khởi tạo")
    
    if bot_engine.is_running:
        return {"status": "already_running", "message": "Bot đang chạy"}
    
    asyncio.create_task(bot_engine.start())
    return {"status": "starting", "message": "Bot đang khởi động..."}


@app.post("/api/bot/stop")
async def stop_bot():
    """Dừng bot"""
    global bot_engine
    if bot_engine is None:
        raise HTTPException(status_code=503, detail="Bot engine chưa được khởi tạo")
    
    await bot_engine.stop()
    return {"status": "stopped", "message": "Bot đã dừng"}


@app.get("/api/bot/status")
async def get_bot_status():
    """Lấy trạng thái bot từ DB"""
    async with get_db() as db:
        result = await db.execute(select(BotStatus).where(BotStatus.id == 1))
        status = result.scalar_one_or_none()
        if not status:
            return {"is_running": False}
        return status.to_dict()


# ─── Account API ─────────────────────────────────────────────────────────────
@app.get("/api/account/balance")
async def get_balance():
    """Lấy số dư tài khoản"""
    global bot_engine
    if bot_engine is None or not bot_engine.exchange.is_connected():
        return {"total": 0, "free": 0, "used": 0, "error": "Chưa kết nối exchange"}
    
    try:
        balance = await bot_engine.exchange.get_balance()
        return balance
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/account/positions")
async def get_positions():
    """Lấy vị thế đang mở"""
    global bot_engine
    if bot_engine is None or not bot_engine.exchange.is_connected():
        return []
    
    try:
        positions = await bot_engine.exchange.get_positions()
        return positions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/account/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Lấy giá hiện tại"""
    global bot_engine
    if bot_engine is None or not bot_engine.exchange.is_connected():
        raise HTTPException(status_code=503, detail="Chưa kết nối exchange")
    
    try:
        ticker = await bot_engine.exchange.fetch_ticker(symbol.upper() + "/USDT")
        return ticker
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Trades API ──────────────────────────────────────────────────────────────
@app.get("/api/trades")
async def get_trades(limit: int = 50, offset: int = 0):
    """Lấy lịch sử giao dịch"""
    async with get_db() as db:
        result = await db.execute(
            select(Trade)
            .order_by(desc(Trade.created_at))
            .limit(limit)
            .offset(offset)
        )
        trades = result.scalars().all()
        return [t.to_dict() for t in trades]


@app.get("/api/trades/stats")
async def get_trade_stats():
    """Thống kê tổng hợp"""
    async with get_db() as db:
        # Tổng P&L
        pnl_result = await db.execute(
            select(func.sum(Trade.realized_pnl)).where(Trade.status == "closed")
        )
        total_pnl = pnl_result.scalar() or 0

        # Win/Loss count
        win_result = await db.execute(
            select(func.count()).where(Trade.realized_pnl > 0, Trade.status == "closed")
        )
        win_count = win_result.scalar() or 0

        loss_result = await db.execute(
            select(func.count()).where(Trade.realized_pnl < 0, Trade.status == "closed")
        )
        loss_count = loss_result.scalar() or 0

        total_closed = win_count + loss_count
        win_rate = round(win_count / total_closed * 100, 2) if total_closed > 0 else 0

        # Trade count by symbol
        symbol_result = await db.execute(
            select(Trade.symbol, func.count(Trade.id).label("count"))
            .group_by(Trade.symbol)
        )
        by_symbol = [{"symbol": row[0], "count": row[1]} for row in symbol_result]

        return {
            "total_pnl": round(total_pnl, 4),
            "total_trades": total_closed,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "by_symbol": by_symbol,
        }


# ─── Signals API ─────────────────────────────────────────────────────────────
@app.get("/api/signals")
async def get_signals(limit: int = 100):
    """Lấy lịch sử tín hiệu"""
    async with get_db() as db:
        result = await db.execute(
            select(Signal)
            .order_by(desc(Signal.timestamp))
            .limit(limit)
        )
        signals = result.scalars().all()
        return [s.to_dict() for s in signals]


# ─── Chart Data API ──────────────────────────────────────────────────────────
@app.get("/api/chart/{symbol}")
async def get_chart_data(symbol: str, timeframe: str = "15m", limit: int = 100):
    """Lấy dữ liệu OHLCV + indicators cho chart"""
    global bot_engine
    if bot_engine is None or not bot_engine.exchange.is_connected():
        raise HTTPException(status_code=503, detail="Chưa kết nối exchange")

    trading_symbol = symbol.upper() + "/USDT"
    
    try:
        from src.data.indicators import ohlcv_to_dataframe, add_indicators_to_df
        config = bot_engine.strategy_config
        
        ohlcv = await bot_engine.exchange.fetch_ohlcv(trading_symbol, timeframe, limit)
        df = ohlcv_to_dataframe(ohlcv)
        df = add_indicators_to_df(
            df,
            ma_fast=config.get("ma_fast", 12),
            ma_slow=config.get("ma_slow", 26),
            ma_type=config.get("ma_type", "EMA"),
        )
        df = df.dropna()
        df = df.reset_index()
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
        
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Config API ──────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    """Lấy cấu hình hiện tại"""
    global bot_engine
    if bot_engine is None:
        return {}
    return {
        "strategy": bot_engine.strategy_config,
        "risk": bot_engine.risk_config,
        "trading": bot_engine.trading_config,
    }


# ─── WebSocket ───────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time updates via WebSocket"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Gửi update mỗi 5 giây
            await asyncio.sleep(5)
            
            global bot_engine
            if bot_engine and bot_engine.exchange.is_connected():
                try:
                    balance = await bot_engine.exchange.get_balance()
                    positions = await bot_engine.exchange.get_positions()
                    
                    async with get_db() as db:
                        result = await db.execute(select(BotStatus).where(BotStatus.id == 1))
                        status = result.scalar_one_or_none()
                    
                    await ws_manager.broadcast({
                        "type": "update",
                        "balance": balance,
                        "positions": positions,
                        "bot_status": status.to_dict() if status else {},
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                except Exception as e:
                    logger.debug(f"WS update error: {e}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
