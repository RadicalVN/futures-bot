# Lịch sử Cập nhật (Update History)

## [2.5.0] - 2026-04-29
### Added
- **EntryOpportunity:** Bảng DB mới lưu tất cả signal entry tìm được, kể cả khi không vào lệnh do giới hạn position. Có cột `is_deleted`, `delete_reason`, `invalidated_at` để track vòng đời.
- **ExitMonitor:** Job quét định kỳ chạy song song với BotEngine:
  - Kiểm tra điều kiện exit (SL/TP cứng + điều kiện chiến lược) cho Trade đang mở
  - Invalidate EntryOpportunity khi điều kiện exit xuất hiện
  - Gửi Discord noti khi đóng lệnh hoặc invalidate opportunity
- **migrate_db.py:** Script migration thêm cột `stop_loss`, `take_profit` vào bảng `trades` và tạo bảng `entry_opportunities`
- **Trade model:** Thêm cột `stop_loss`, `take_profit` — lưu khi mở lệnh, dùng cho ExitMonitor

## [2.4.0] - 2026-04-29
### Added
- **Lệnh & PnL tab:** Trang mới hiển thị vị thế đang mở, lịch sử giao dịch, thống kê từng bot
  - Cột Bot và Chiến lược cho mỗi trade
  - Unrealized PnL từ exchange, auto-refresh 30s
  - Timezone UTC+7 (Asia/Ho_Chi_Minh)
- **Dynamic max_positions:** Tính giới hạn vị thế động theo `max_portfolio_risk_pct` thay vì fix cứng
- **Always analyze:** Bot luôn analyze tất cả symbol dù đã đạt giới hạn — chỉ block đặt lệnh, không block signal/noti
- **Per-bot logging:** Mỗi bot có file log riêng `logs/bot_{id}_{name}/YYYY-MM-DD.log`, rotation theo ngày
- **Discord report gộp:** BotManager coordinator gộp report 5m của tất cả bot thành 1 message — tránh rate limit
- **Candle status report:** Mỗi nến 5m đóng gửi Discord report với điều kiện đã thỏa/còn thiếu cho từng bot
### Fixed
- **strategy_name:** Không còn lưu "unknown" vào Trade — lấy đúng từ `bot.strategy_name`
- **realized_pnl:** Lưu đúng vào Trade record khi đóng lệnh
- **Position symbol matching:** Normalize `BTC/USDT:USDT` → `BTCUSDT` khi so sánh
- **amount_precision:** Convert step size (0.001) sang decimal places (3) đúng cách
- **Tab restore:** Reload trang giữ nguyên tab đang xem (localStorage)

## [2.3.0] - 2026-04-28
### Added
- **Full traceback logging:** Mọi exception đều log đầy đủ stack trace vào file bot
- **Error signal:** Khi strategy crash, tạo error signal với traceback để hiển thị trên Discord report
- **Insufficient data detection:** Phát hiện và noti khi thiếu dữ liệu OHLCV hoặc strategy báo không đủ data
- **Discord retry:** Retry với exponential backoff cho lỗi 5xx và connection failure
- **Separate Discord channels:** `DISCORD_WEBHOOK_URL` cho entry/exit, `DISCORD_REPORT_WEBHOOK_URL` cho báo cáo định kỳ
### Fixed
- **positionRisk API:** Fallback với `params={"type": "2"}` khi Demo Trading không hỗ trợ endpoint mặc định
- **Symbol normalize:** `BTCUSDT` → `BTC/USDT`, `TRUMPUSDT` → `TRUMP/USDT`

## [2.2.0] - 2026-04-28
### Added
- **Multi-bot support:** BotManager quản lý nhiều BotEngine chạy song song
- **Custom SMA strategies:** 3 chiến lược mới dựa trên chỉ báo SMA tùy chỉnh:
  - `sma_trend_early_exit`: Thuận xu hướng + thoát sớm khi momentum suy yếu
  - `sma_pullback`: Bắt đáy sóng hồi
  - `sma_anti_sideway`: Lọc thị trường sideway bằng slope
- **Condition report:** Discord report hiển thị điều kiện đã thỏa/còn thiếu với ngưỡng cụ thể
- **Market symbol cache:** Cache 10 phút cho `/api/symbols` tránh gọi API liên tục

## [2.1.0] - 2026-04-27
### Added
- **Multi-account:** Quản lý nhiều API key độc lập
- **Soft delete:** Bot bị xóa vẫn giữ lịch sử giao dịch
- **Bot stats:** Tổng hợp PnL, win rate, số lệnh theo từng bot
### Fixed
- **Binance Demo Trading:** Chuyển từ testnet sang demo-fapi.binance.com

## [2.0.0] - 2026-04-26
### Added
- **Multi-bot platform:** Chuyển từ single-bot script sang nền tảng quản lý nhiều bot
- **Database:** SQLite + SQLAlchemy ORM với các bảng Bot, Trade, Signal, BotEvent, ExchangeAccount
- **Dashboard V2:** ES6 Modules, FastAPI Routers, Pydantic schemas
- **Strategy marketplace:** UI chọn và cấu hình chiến lược
- **Risk management:** Position sizing, SL/TP tự động, trailing stop

## [1.1.0] - 2026-04-26
### Added
- **UI:** Nâng cấp biểu đồ giá mặc định trên Dashboard sang dạng Nến Nhật (Candlestick)
- **Docs:** Tạo thư mục docs/ và bổ sung tài liệu kiến trúc, lịch sử cập nhật
### Fixed
- **Network:** Gỡ bỏ thư viện iodns để sửa lỗi DNS trên Windows

## [1.0.0] - 2026-04-25
### Added
- **Core:** Khởi tạo Trading Engine kết nối Binance qua ccxt
- **Strategy:** Hoàn thiện thuật toán MA + MACD
- **Dashboard:** Xây dựng hệ thống backend FastAPI và Web UI tĩnh
- **Setup:** Script start.bat để cài đặt và chạy nhanh trên Windows
- **Deploy:** Chuẩn bị sẵn Docker cấu hình
