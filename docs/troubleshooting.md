# Troubleshooting — Hướng dẫn xử lý lỗi

## Vấn đề: Bot không vào lệnh và không có thông báo Discord

### Nguyên nhân chính

**Lỗi API `positionRisk` trên Demo Trading:**
```
Lỗi _run_cycle: binanceusdm GET https://demo-fapi.binance.com/fapi/v3/positionRisk
```

Khi `get_positions()` lỗi, toàn bộ chu kỳ quét bị bỏ qua → không có signal → không vào lệnh → không có Discord.

### Đã fix (commit d8dfc18)

1. **Bắt lỗi `get_positions()` trong `_run_cycle`** — nếu lỗi chỉ bỏ qua chu kỳ đó, không crash bot
2. **Thêm fallback trong `exchange.get_positions()`** — thử lại với `params={"type": "2"}` nếu lỗi lần đầu
3. **Fix hardcode `strategy="ma_macd"`** — giờ lấy từ `config["strategy_name"]`
4. **Thêm `DISCORD_WEBHOOK_URL` vào `.env.example`**

### Kiểm tra Discord Webhook

Đảm bảo file `.env` có dòng:
```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

Nếu để trống → Discord im lặng (không lỗi, chỉ không gửi).

### Kiểm tra log

Sau khi restart bot, log phải có:
```
BotEngine [ID: X] sẵn sàng. Quét Y cặp mỗi 60s
```

Nếu thấy lỗi `positionRisk` lặp lại → API key có thể không hợp lệ hoặc Demo Trading có vấn đề.

---

## Vấn đề: Điều kiện entry quá khắt khe

### Chiến lược 1: `sma_trend_early_exit`

**Entry LONG:**
- Trend vừa đảo từ -1 → 1 (đúng 1 nến)
- Momentum phải là `blue` hoặc `purple`
- `|slope_pct| >= min_slope_pct` (mặc định 0.0)

**Nếu không vào lệnh:**
- Giảm `min_slope_pct` xuống 0 (hoặc âm để bỏ qua hoàn toàn)
- Kiểm tra xem Trend có thực sự đảo chiều không (xem log signal)

### Chiến lược 2: `sma_pullback`

**Entry LONG:**
- Trend đang = 1 (không cần đảo chiều)
- N nến trước (mặc định 2) có momentum = `orange/yellow/green`
- Nến hiện tại momentum = `blue/purple`

**Nếu không vào lệnh:**
- Giảm `pullback_confirm_bars` xuống 1
- Giảm `min_slope_pct` xuống 0

### Chiến lược 3: `sma_anti_sideway`

**Entry LONG:**
- `|slope_pct| >= sideway_slope_threshold` (mặc định 0.01%) — **bộ lọc tiên quyết**
- Trend vừa đảo từ -1 → 1
- `|momentum_pct| >= min_momentum_pct` (mặc định 0.0)

**Nếu không vào lệnh:**
- Giảm `sideway_slope_threshold` xuống 0.001 hoặc 0
- Giảm `min_momentum_pct` xuống 0

---

## Vấn đề: Timeframe không phù hợp

Mặc định hiện tại: **5m** (sau commit 8856017)

Nếu muốn đổi:
1. Sửa `config.yaml` → `timeframe: "15m"`
2. Hoặc sửa từng bot trong dashboard → Parameters → `"timeframe": "1h"`

Timeframe ngắn (1m, 5m) → nhiều tín hiệu nhưng nhiễu cao
Timeframe dài (1h, 4h) → ít tín hiệu nhưng chất lượng cao hơn

---

## Debug nhanh

### Xem signal gần nhất
```sql
SELECT * FROM signals ORDER BY timestamp DESC LIMIT 20;
```

### Xem bot đang chạy
```sql
SELECT id, name, strategy_name, status FROM bots WHERE is_deleted=0;
```

### Xem log realtime
```bash
tail -f logs/trading.log
```

### Test Discord webhook
```bash
curl -X POST "YOUR_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"content": "Test từ trading bot"}'
```
