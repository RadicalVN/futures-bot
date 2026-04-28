import asyncio
import aiohttp

WEBHOOK = 'https://discord.com/api/webhooks/1498434298469027932/WSlePfs47AHiCqqNK57-VB8a4JkvJhmKBl_EWPJxDR5e0fqZTnLwmYb6rIQpeqSsgaQu'

SAMPLES = [
    {
        "type": "entry",
        "id": 1, "symbol": "BTCUSDT", "strategy": "TVT-EarlyExit",
        "signal": "long", "label": "MO LONG",
        "color": 0x00C853,
        "entry": 93450.20, "amount": 0.005, "leverage": 5,
        "sl": 92080.50, "tp": 95820.80,
        "reason": "Mo LONG: Trend Tang + Gia toc manh (blue) | Slope=+0.0031%"
    },
    {
        "type": "entry",
        "id": 2, "symbol": "TRUMPUSDT", "strategy": "TVT-EarlyExit",
        "signal": "short", "label": "MO SHORT",
        "color": 0xF6465D,
        "entry": 14.382, "amount": 120.0, "leverage": 5,
        "sl": 14.721, "tp": 13.705,
        "reason": "Mo SHORT: Trend Giam + Gia toc manh (blue) | Slope=-0.0145%"
    },
    {
        "type": "entry",
        "id": 3, "symbol": "BTCUSDT", "strategy": "TVT-Pullback",
        "signal": "long", "label": "MO LONG [Pullback]",
        "color": 0x00E676,
        "entry": 92870.50, "amount": 0.005, "leverage": 5,
        "sl": 91520.30, "tp": 95410.20,
        "reason": "Mo LONG pullback: Trend Xanh + Hoi 2 nen + Bat (purple) | Slope=+0.0028%"
    },
    {
        "type": "exit",
        "id": 4, "symbol": "TRUMPUSDT", "strategy": "TVT-Pullback",
        "signal": "close_short", "label": "DONG SHORT [Pullback]",
        "color": 0x00C853,
        "close_price": 14.102, "pnl": "+34.88",
        "reason": "Dong SHORT som: Trend dao Xanh | Gia toc tang manh (blue)"
    },
    {
        "type": "sideway",
        "id": 5, "symbol": "BTCUSDT", "strategy": "TVT-AntiSideway",
        "signal": "none", "label": "NGU DONG [Sideway]",
        "color": 0x546E7A,
        "reason": "Ngu dong (Sideway): |Slope|=0.0032% < nguong 0.005% | Momentum=yellow"
    },
    {
        "type": "entry",
        "id": 6, "symbol": "TRUMPUSDT", "strategy": "TVT-AntiSideway",
        "signal": "short", "label": "MO SHORT [Anti-Sideway]",
        "color": 0xF6465D,
        "entry": 13.954, "amount": 150.0, "leverage": 5,
        "sl": 14.372, "tp": 13.118,
        "reason": "Mo SHORT: Trend Giam | Slope=-0.0182% (manh) | MomPct=-0.0091%"
    },
]


def build_embed(b: dict) -> dict:
    t = b["type"]
    icon = "🟢" if b["signal"] == "long" else ("🔴" if b["signal"] == "short" else ("🔒" if "close" in b["signal"] else "😴"))

    if t == "entry":
        return {
            "title": f"{icon} {b['label']} — Bot #{b['id']} | {b['symbol']}",
            "description": f"**Strategy**: `{b['strategy']}`",
            "color": b["color"],
            "fields": [
                {"name": "💰 Giá vào",     "value": f"`{b['entry']:,.4f} USDT`", "inline": True},
                {"name": "📦 Khối lượng",  "value": f"`{b['amount']}`",           "inline": True},
                {"name": "⚙️ Đòn bẩy",    "value": f"`{b['leverage']}x`",        "inline": True},
                {"name": "🛑 Stop Loss",   "value": f"`{b['sl']:,.4f}`",          "inline": True},
                {"name": "🎯 Take Profit", "value": f"`{b['tp']:,.4f}`",          "inline": True},
                {"name": "📝 Lý do",       "value": b["reason"],                   "inline": False},
            ],
            "footer": {"text": "Trading Bot — ittuantruong"},
        }
    elif t == "exit":
        pnl = float(b["pnl"])
        color = 0x00C853 if pnl > 0 else 0xF6465D
        return {
            "title": f"{icon} {b['label']} — Bot #{b['id']} | {b['symbol']}",
            "description": f"**Strategy**: `{b['strategy']}`",
            "color": color,
            "fields": [
                {"name": "💸 Giá đóng", "value": f"`{b['close_price']}`",        "inline": True},
                {"name": "💵 PnL",      "value": f"`{b['pnl']} USDT`",           "inline": True},
                {"name": "📝 Lý do",    "value": b["reason"],                     "inline": False},
            ],
            "footer": {"text": "Trading Bot — ittuantruong"},
        }
    else:
        return {
            "title": f"{icon} {b['label']} — Bot #{b['id']} | {b['symbol']}",
            "description": f"**Strategy**: `{b['strategy']}`",
            "color": b["color"],
            "fields": [
                {"name": "📊 Trạng thái", "value": "`Không có tín hiệu`", "inline": True},
                {"name": "📝 Lý do",      "value": b["reason"],            "inline": False},
            ],
            "footer": {"text": "Trading Bot — ittuantruong"},
        }


async def main():
    async with aiohttp.ClientSession() as session:
        for b in SAMPLES:
            embed = build_embed(b)
            async with session.post(WEBHOOK, json={"embeds": [embed]}) as r:
                print(f"Bot #{b['id']} {b['symbol']} [{b['strategy']}] -> {r.status}")
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
