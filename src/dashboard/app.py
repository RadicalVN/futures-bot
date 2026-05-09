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
import pandas as pd

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


# --- Include API Routers ---
from src.dashboard.routers import accounts, bots, data, market, backtest, market_data
from src.dashboard.routers import ai as ai_router
from src.dashboard.routers import strategies as strategies_router
from src.dashboard.routers import analytics as analytics_router

app.include_router(accounts.router)
app.include_router(bots.router)
app.include_router(data.router)
app.include_router(market.router)
app.include_router(backtest.router)
app.include_router(market_data.router)
app.include_router(ai_router.router)
app.include_router(strategies_router.router)
app.include_router(analytics_router.router)

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
