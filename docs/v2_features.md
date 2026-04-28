# Tính năng & Bố cục UI - V2 Multi-Bot Platform

## 1. Bố cục Giao diện Web (UI Layout)

### Tab 1: 📊 Tổng Quan (Dashboard)
- Thống kê: Tổng PnL, số bot đang chạy, win rate
- Biểu đồ nến nhật đôi (2 chart song song) với Custom SMA + MACD
- Lịch sử giao dịch gần nhất và nhật ký hệ thống

### Tab 2: 🤖 Danh Sách Bot
- Card từng bot: trạng thái, symbol, PnL, win rate
- Bật/Tắt/Xóa bot (soft delete)

### Tab 3: 📋 Lệnh & PnL
- **Vị thế đang mở:** Unrealized PnL từ exchange, auto-refresh 30s
- **Thống kê từng bot:** Lệnh mở/đóng, win rate, PnL
- **Lịch sử giao dịch:** Filter theo bot/status/symbol, cột Bot và Chiến lược
- Timezone UTC+7, tab restore khi reload

### Tab 4: 📈 Chỉ Báo Kỹ Thuật
- Toggle bật/tắt Custom SMA, Custom MACD trên biểu đồ

### Tab 5: 🎯 Chiến Lược Giao Dịch
- Danh sách chiến lược có sẵn
- Form khởi tạo bot với tham số JSON

### Tab 6: ⚙️ Cài Đặt
- Quản lý nhiều API key (testnet/mainnet)

---

## 2. Kiến Trúc Backend

### Multi-Bot Engine
- **BotManager:** Quét DB mỗi 5s, spawn/kill BotEngine theo trạng thái
- **BotEngine:** Mỗi bot chạy độc lập trong asyncio task
- **Report Coordinator:** Gộp report 5m của tất cả bot thành 1 Discord message tránh rate limit

### Per-Bot Logging
```
logs/
├── trading.log                    ← log chung
└── bot_{id}_{name}/
    └── YYYY-MM-DD.log             ← log riêng từng bot, rotation theo ngày
```

### ExitMonitor (mới - v2.5)
Job chạy song song với mỗi BotEngine, mỗi chu kỳ:
1. Kiểm tra Trade đang mở → đóng nếu thỏa điều kiện exit
2. Kiểm tra EntryOpportunity → invalidate nếu cơ hội đã qua
3. Gửi Discord noti

Điều kiện exit được check theo thứ tự:
- SL/TP cứng (stop_loss, take_profit từ khi mở lệnh)
- Điều kiện chiến lược (trend đảo, momentum suy yếu, sideway...)

### EntryOpportunity (mới - v2.5)
Lưu tất cả signal entry tìm được, kể cả khi không vào lệnh:
```
entry_opportunities:
  - bot_id, symbol, signal_type (long/short)
  - strategy, entry_price, stop_loss, take_profit
  - executed: True nếu đã vào lệnh thực tế
  - is_deleted: True nếu điều kiện exit đã xuất hiện
  - delete_reason: Lý do invalidate
  - metadata: slope, momentum, trend tại thời điểm tìm thấy
```

---

## 3. Chiến Lược Giao Dịch

### Custom SMA Indicator
Chỉ báo tùy chỉnh tính từ SMA nhanh + chậm, làm mượt, tạo dải Bollinger:
- **Trend:** 1 (tăng) / -1 (giảm)
- **Momentum:** blue/purple (mạnh) | orange/yellow/green (hồi) | red (giảm mạnh)
- **Slope %:** Độ dốc của SMA basis

### Chiến Lược 1: `sma_trend_early_exit`
- **Entry:** Trend vừa đảo chiều + Momentum mạnh (blue/purple)
- **Exit sớm:** Momentum suy yếu (orange/yellow/green) — không chờ trend đổi màu
- **Params:** `min_slope_pct`

### Chiến Lược 2: `sma_pullback`
- **Entry:** Trend đang chạy + N nến hồi (momentum yếu) + Momentum bật mạnh trở lại
- **Exit:** Trend đảo hoặc momentum mạnh ngược chiều
- **Params:** `pullback_confirm_bars`, `min_slope_pct`

### Chiến Lược 3: `sma_anti_sideway`
- **Entry:** Slope đủ mạnh (không sideway) + Trend vừa đảo chiều
- **Exit:** Slope thu hẹp (về sideway) hoặc trend đảo
- **Params:** `sideway_slope_threshold`, `exit_slope_threshold`, `min_momentum_pct`

---

## 4. Risk Management

### Position Sizing
```
amount = (balance * position_size_pct * leverage) / entry_price
```

### Dynamic Max Positions (mới - v2.4)
```
max_positions = max_portfolio_risk_pct / (position_size_pct * stop_loss_pct)
```
Nếu không set `max_portfolio_risk_pct` → dùng `max_open_positions` cố định.

### Tham số Risk (trong bot parameters)
| Param | Default | Mô tả |
|-------|---------|-------|
| `leverage` | 5 | Đòn bẩy |
| `position_size_pct` | 0.10 | % số dư mỗi lệnh |
| `stop_loss_pct` | 0.02 | SL 2% |
| `take_profit_pct` | 0.04 | TP 4% |
| `margin_mode` | isolated | Chế độ margin |
| `max_open_positions` | 1 | Giới hạn vị thế cố định |
| `max_portfolio_risk_pct` | — | Giới hạn rủi ro động (nếu set sẽ override max_open_positions) |

---

## 5. Discord Notifications

### Channels
- `DISCORD_WEBHOOK_URL`: Entry/exit lệnh thực tế, lỗi đặt lệnh
- `DISCORD_REPORT_WEBHOOK_URL`: Báo cáo định kỳ mỗi nến 5m, invalidate opportunity

### Loại thông báo
| Loại | Channel | Mô tả |
|------|---------|-------|
| 🟢 MỞ LONG / 🔴 MỞ SHORT | Entry | Vào lệnh thành công |
| 🔒 ĐÓNG LONG/SHORT | Entry | Đóng lệnh + PnL |
| ⚠️ Lỗi đặt lệnh | Entry | Lỗi khi đặt lệnh |
| 📊 Báo cáo nến 5m | Report | Trạng thái tất cả bot, điều kiện đã thỏa/còn thiếu |
| 🗑️ Cơ hội hết hạn | Report | EntryOpportunity bị invalidate |

---

## 6. Database Schema

```
ExchangeAccount  ← API keys
Bot              ← Cấu hình bot (strategy, symbols, parameters)
Trade            ← Lệnh đã đặt (stop_loss, take_profit, realized_pnl)
EntryOpportunity ← Tất cả signal entry tìm được (executed, is_deleted)
Signal           ← Lịch sử tín hiệu indicator
BotEvent         ← Log sự kiện bot
```
