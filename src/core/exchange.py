"""
exchange.py — Binance API Wrapper using ccxt
Hỗ trợ Futures (USDT-M) và Spot trên cả Demo Trading và Mainnet

Lưu ý: Binance đã ngừng sandbox Futures testnet từ 2024.
Thay thế bằng Demo Trading (demoAccount=True) theo thông báo:
https://t.me/ccxt_announcements/92
"""
import os
import asyncio
from typing import Optional
import ccxt.async_support as ccxt
from loguru import logger


class BinanceExchange:
    """
    Wrapper cho ccxt binance/binanceusdm
    Tự động chọn Testnet/Mainnet dựa trên BINANCE_MODE env var
    """

    def __init__(self, api_key: str, api_secret: str, mode: str = "testnet", market_type: str = "futures"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.mode = mode.lower()  # "testnet" hoặc "mainnet"
        self.market_type = market_type.lower()  # "futures" hoặc "spot"
        self._exchange: Optional[ccxt.Exchange] = None

    async def connect(self):
        """Khởi tạo kết nối đến Binance"""
        params = {
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future" if self.market_type == "futures" else "spot",
            },
        }

        if self.market_type == "futures":
            if self.mode == "testnet":
                # Binance Demo Futures endpoint: https://demo-fapi.binance.com
                # Ref: https://demo.binance.com/en/my/settings/api-management
                demo_base = "https://demo-fapi.binance.com"
                params["options"].update({
                    "recvWindow": 60000,
                    "adjustForTimeDifference": True,
                    "fetchMarketsType": "future",  # Chỉ load future markets, không gọi sapi mainnet
                    "fetchPositionMode": False,     # Bỏ qua check hedge mode khi init
                })
                params["urls"] = {
                    "api": {
                        "fapiPublic":       f"{demo_base}/fapi/v1",
                        "fapiPublicV2":     f"{demo_base}/fapi/v2",
                        "fapiPublicV3":     f"{demo_base}/fapi/v3",
                        "fapiPrivate":      f"{demo_base}/fapi/v1",
                        "fapiPrivateV2":    f"{demo_base}/fapi/v2",
                        "fapiPrivateV3":    f"{demo_base}/fapi/v3",
                        "fapiData":         f"{demo_base}/futures/data",
                    }
                }
                self._exchange = ccxt.binanceusdm(params)
                # Đồng bộ thời gian với server Binance Demo (tránh lệch timestamp)
                await self._exchange.load_time_difference()
                logger.info("🧪 Kết nối Binance DEMO TRADING Futures (demo-fapi.binance.com)")
            else:
                self._exchange = ccxt.binanceusdm(params)
                logger.info("🔴 Kết nối Binance MAINNET Futures (tiền thật!)")
        else:
            self._exchange = ccxt.binance(params)
            if self.mode == "testnet":
                # Spot vẫn hỗ trợ sandbox mode bình thường
                self._exchange.set_sandbox_mode(True)
                logger.info("🧪 Kết nối Binance TESTNET Spot (tiền ảo)")
            else:
                logger.info("🔴 Kết nối Binance MAINNET Spot (tiền thật!)")

        # Load markets — Demo mode dùng fetch_markets trực tiếp để tránh ccxt
        # gọi thêm các endpoint sapi mainnet (không hợp lệ với Demo API key)
        if self.market_type == "futures" and self.mode == "testnet":
            markets = await self._exchange.fetch_markets()
            self._exchange.set_markets(markets)
        else:
            await self._exchange.load_markets()
        logger.info(f"✅ Đã kết nối thành công — Market: {self.market_type.upper()}")

    async def close(self):
        """Đóng kết nối"""
        if self._exchange:
            await self._exchange.close()
            logger.info("Đã đóng kết nối exchange")

    # ─── Account Info ─────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """Lấy số dư tài khoản"""
        balance = await self._exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        return {
            "total": usdt.get("total", 0),
            "free": usdt.get("free", 0),
            "used": usdt.get("used", 0),
        }

    async def get_positions(self) -> list[dict]:
        """Lấy danh sách vị thế đang mở (Futures)"""
        if self.market_type != "futures":
            return []
        try:
            positions = await self._exchange.fetch_positions()
        except Exception as e:
            # Demo Trading đôi khi không hỗ trợ /fapi/v3/positionRisk
            # Thử lại với params type=2 (USDT-M hedge mode off)
            try:
                positions = await self._exchange.fetch_positions(params={"type": "2"})
            except Exception as e2:
                logger.warning(f"get_positions fallback cũng lỗi: {e2}")
                return []
        # Chỉ trả về vị thế có size > 0
        open_positions = [
            {
                "symbol": p["symbol"],
                "side": p["side"],
                "size": p["contracts"],
                "entry_price": p["entryPrice"],
                "unrealized_pnl": p["unrealizedPnl"],
                "leverage": p["leverage"],
                "margin_mode": p["marginMode"],
                "liquidation_price": p.get("liquidationPrice"),
                "percentage": p.get("percentage"),
            }
            for p in positions
            if p.get("contracts") and abs(p["contracts"]) > 0
        ]
        return open_positions

    # ─── Market Data ───────────────────────────────────────────────────────────

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200, params: dict = None) -> list:
        """
        Lấy dữ liệu nến OHLCV
        Returns: list of [timestamp, open, high, low, close, volume]
        """
        params = params or {}
        ohlcv = await self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, params=params)
        return ohlcv

    async def fetch_ticker(self, symbol: str) -> dict:
        """Lấy giá ticker hiện tại"""
        ticker = await self._exchange.fetch_ticker(symbol)
        return {
            "symbol": ticker["symbol"],
            "last": ticker["last"],
            "bid": ticker["bid"],
            "ask": ticker["ask"],
            "volume": ticker["baseVolume"],
            "change_pct": ticker.get("percentage"),
        }

    # ─── Orders ────────────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int):
        """Đặt đòn bẩy cho symbol (Futures only)"""
        if self.market_type != "futures":
            return
        try:
            await self._exchange.set_leverage(leverage, symbol)
            logger.info(f"Đặt leverage {leverage}x cho {symbol}")
        except Exception as e:
            logger.warning(f"set_leverage lỗi: {e}")

    async def set_margin_mode(self, symbol: str, mode: str = "isolated"):
        """Đặt margin mode: 'isolated' hoặc 'cross'"""
        if self.market_type != "futures":
            return
        try:
            await self._exchange.set_margin_mode(mode, symbol)
            logger.info(f"Đặt margin mode '{mode}' cho {symbol}")
        except Exception as e:
            logger.warning(f"set_margin_mode lỗi (có thể đã được đặt rồi): {e}")

    async def create_market_order(
        self, symbol: str, side: str, amount: float, params: dict = None
    ) -> dict:
        """
        Tạo Market Order
        side: 'buy' (Long) hoặc 'sell' (Short)
        amount: số lượng contract
        """
        params = params or {}
        order = await self._exchange.create_market_order(symbol, side, amount, params=params)
        logger.info(f"📋 Market Order — {side.upper()} {amount} {symbol} | ID: {order['id']}")
        return order

    async def create_limit_order(
        self, symbol: str, side: str, amount: float, price: float, params: dict = None
    ) -> dict:
        """Tạo Limit Order"""
        params = params or {}
        order = await self._exchange.create_limit_order(symbol, side, amount, price, params=params)
        logger.info(f"📋 Limit Order — {side.upper()} {amount} {symbol} @ {price} | ID: {order['id']}")
        return order

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Hủy lệnh"""
        result = await self._exchange.cancel_order(order_id, symbol)
        logger.info(f"❌ Đã hủy lệnh {order_id}")
        return result

    async def fetch_open_orders(self, symbol: str = None) -> list[dict]:
        """Lấy danh sách lệnh đang chờ"""
        orders = await self._exchange.fetch_open_orders(symbol)
        return orders

    async def get_order_status(self, order_id: str, symbol: str) -> dict:
        """Kiểm tra trạng thái lệnh"""
        order = await self._exchange.fetch_order(order_id, symbol)
        return {
            "id": order["id"],
            "symbol": order["symbol"],
            "side": order["side"],
            "amount": order["amount"],
            "filled": order["filled"],
            "status": order["status"],
            "price": order["price"],
            "average": order["average"],
            "cost": order["cost"],
        }

    async def close_position(self, symbol: str, side: str, amount: float) -> dict:
        """
        Đóng vị thế Futures
        side: vị thế đang giữ ('long' hoặc 'short')
        """
        # Đóng Long → Sell; Đóng Short → Buy
        close_side = "sell" if side == "long" else "buy"
        params = {"reduceOnly": True}
        order = await self.create_market_order(symbol, close_side, amount, params=params)
        logger.info(f"🔒 Đóng vị thế {side.upper()} {symbol} — amount: {amount}")
        return order

    # ─── Utility ───────────────────────────────────────────────────────────────

    async def get_symbol_info(self, symbol: str) -> dict:
        """Lấy thông tin symbol (tick size, lot size, ...)"""
        market = self._exchange.market(symbol)

        def _step_to_decimals(step) -> int:
            """
            Chuyển step size sang số chữ số thập phân.
            ccxt trả về precision dạng step size: 0.001 → 3, 0.01 → 2, 1 → 0, 3 → 0
            Nếu step >= 1 thì precision = 0 (số nguyên).
            """
            if step is None:
                return 3
            step = float(step)
            if step >= 1:
                return 0
            # Đếm số chữ số thập phân từ step size
            import math
            decimals = max(0, -int(math.floor(math.log10(step))))
            return decimals

        return {
            "symbol": symbol,
            "base": market["base"],
            "quote": market["quote"],
            "min_amount": market["limits"]["amount"]["min"] or 0.0,
            "amount_precision": _step_to_decimals(market["precision"]["amount"]),
            "price_precision": _step_to_decimals(market["precision"]["price"]),
            "contract_size": market.get("contractSize", 1),
        }

    def is_connected(self) -> bool:
        return self._exchange is not None


def create_exchange_from_env() -> BinanceExchange:
    """Factory function — tạo exchange từ biến môi trường"""
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    mode = os.getenv("BINANCE_MODE", "testnet")

    if not api_key or api_key == "your_api_key_here":
        raise ValueError(
            "❌ Chưa cấu hình BINANCE_API_KEY!\n"
            "Hãy copy file .env.example thành .env và điền API key của bạn."
        )

    return BinanceExchange(api_key=api_key, api_secret=api_secret, mode=mode)
