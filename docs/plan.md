# Kế hoạch Triển khai (Implementation Plan)

## Tầm nhìn Hệ thống
Phát triển từ **Single Trading Script** thành **Nền tảng Quản lý Bot**, cho phép khởi tạo, quản lý và vận hành song song nhiều bot trên các cặp giao dịch và chiến thuật khác nhau.

---

## Phase 1: Nền tảng Cơ bản ✅ HOÀN THÀNH
- [x] Core Engine: ccxt.async_support + asyncio
- [x] Dashboard: FastAPI + uvicorn
- [x] Database: SQLite + SQLAlchemy ORM
- [x] Frontend: Vanilla JS, Chart.js Candlestick
- [x] Strategy: MA + MACD

## Phase 2: Multi-Bot Platform ✅ HOÀN THÀNH
- [x] BotManager: Quản lý lifecycle nhiều BotEngine
- [x] Database schema: Bot, Trade, Signal, BotEvent, ExchangeAccount
- [x] Dashboard V2: ES6 Modules, FastAPI Routers, Pydantic
- [x] Strategy marketplace UI
- [x] Risk management: Position sizing, SL/TP, trailing stop
- [x] Custom SMA indicator + 3 chiến lược
- [x] Per-bot logging (tách file theo ngày)
- [x] Discord notifications (entry/exit + báo cáo 5m)

## Phase 3: Monitoring & Intelligence ✅ HOÀN THÀNH
- [x] ExitMonitor: Job quét định kỳ đóng lệnh theo điều kiện chiến lược
- [x] EntryOpportunity: Lưu tất cả signal entry, track vòng đời với is_deleted
- [x] Dynamic max_positions theo rủi ro vốn (max_portfolio_risk_pct)
- [x] Always analyze: Không bỏ qua symbol dù đạt giới hạn position
- [x] Full traceback logging + error Discord noti
- [x] Lệnh & PnL tab: Unrealized PnL, bot/strategy columns, timezone +7
- [x] Report coordinator: Gộp report tránh Discord rate limit

## Phase 4: Tối ưu & Mở rộng (KẾ HOẠCH)
- [ ] Backtesting engine
- [ ] Telegram notifications
- [ ] Strategy performance analytics
- [ ] Auto-tune parameters
- [ ] WebSocket real-time updates cho dashboard
