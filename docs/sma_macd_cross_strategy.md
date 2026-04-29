# Chiến lược SMA + MACD Cross (TVT-SMA+MACD)

---

## Phần 1 — Mô tả gốc

### Entry LONG
**Điều kiện 1:** MACD-Signal chuyển từ đỏ/cam sang tím/xanh lá/xanh dương
**và Điều kiện 2:** MACD phải cắt qua MACD-Signal từ dưới lên
**và Điều kiện 3:** Giá/nến phải cắt qua MA, kết thúc nến giá phải nằm trên MA
→ Giá mua tiệm cận đường MA

**Exit LONG (ExitMonitor check):**
- Có nến sau điểm mua kết thúc phiên giá nằm dưới đường MA → đóng ngay
- Hoặc MA chuyển đỏ/cam → đóng ngay
- Hoặc MACD-Signal chuyển đỏ/cam → đóng ngay
- Hoặc có phiên MACD đỏ, MA xanh lá → đóng ngay

---

### Entry SHORT
**Điều kiện 1:** MACD-Signal chuyển từ xanh dương/xanh lá sang tím/đỏ/cam
**và Điều kiện 2:** MACD phải cắt qua MACD-Signal từ trên xuống
**và Điều kiện 3:** Giá/nến phải cắt qua MA, kết thúc nến giá phải nằm dưới MA
→ Giá bán tiệm cận đường MA

**Exit SHORT (ExitMonitor check):**
- Có nến sau điểm bán kết thúc phiên giá nằm trên đường MA → đóng ngay
- Hoặc MA chuyển xanh dương/xanh lá → đóng ngay
- Hoặc MACD-Signal chuyển xanh dương/xanh lá → đóng ngay
- Hoặc có phiên MACD xanh dương, MA cam → đóng ngay

---

## Phần 2 — Mô tả theo ngôn ngữ trader

### Tổng quan
Chiến lược kết hợp **đường trung bình động (MA)** và **MACD** để xác nhận điểm vào lệnh với 3 lớp xác nhận độc lập, nhằm giảm thiểu tín hiệu giả. Giá vào lệnh được đặt tiệm cận đường MA — tức là mua/bán ở vùng hỗ trợ/kháng cự động, giúp tối ưu tỷ lệ Risk/Reward.

---

### Entry LONG (Mua)

**Bối cảnh:** Thị trường đang trong giai đoạn điều chỉnh (MACD-Signal đang yếu/giảm), chuẩn bị phục hồi.

**3 điều kiện xác nhận:**

1. **Momentum MACD-Signal đảo chiều tăng**
   MACD-Signal đang trong trạng thái suy yếu (giảm tốc hoặc đảo chiều xuống) chuyển sang trạng thái tăng tốc hoặc đảo chiều lên. Đây là dấu hiệu đầu tiên cho thấy lực bán đang cạn kiệt.

2. **MACD cắt lên Signal (Golden Cross)**
   Đường MACD cắt lên trên đường Signal — xác nhận momentum ngắn hạn đã mạnh hơn momentum dài hạn, tín hiệu tăng được xác nhận.

3. **Giá phá vỡ và đóng cửa trên MA**
   Nến hiện tại phá vỡ đường MA từ dưới lên và đóng cửa phía trên — xác nhận giá đã vượt qua ngưỡng kháng cự động, xu hướng tăng được thiết lập.

**Giá vào:** Tiệm cận đường MA (mua gần vùng hỗ trợ động, rủi ro thấp).

**Thoát lệnh LONG — bất kỳ 1 trong 4 điều kiện:**

| Điều kiện | Ý nghĩa |
|-----------|---------|
| Giá đóng cửa dưới MA | Giá đã phá vỡ hỗ trợ động — xu hướng tăng thất bại |
| MA chuyển sang suy yếu (đỏ/cam) | Đường MA đang dốc xuống — xu hướng tăng đang mất đà |
| MACD-Signal chuyển sang suy yếu | Momentum tổng thể đang đảo chiều xuống |
| MACD đỏ + MA xanh lá | Phân kỳ giảm: momentum ngắn hạn giảm trong khi MA vẫn tăng nhẹ — cảnh báo sớm đảo chiều |

---

### Entry SHORT (Bán)

**Bối cảnh:** Thị trường đang trong giai đoạn hồi phục (MACD-Signal đang mạnh/tăng), chuẩn bị quay đầu giảm.

**3 điều kiện xác nhận:**

1. **Momentum MACD-Signal đảo chiều giảm**
   MACD-Signal đang trong trạng thái tăng tốc chuyển sang suy yếu hoặc đảo chiều xuống. Dấu hiệu đầu tiên cho thấy lực mua đang cạn kiệt.

2. **MACD cắt xuống Signal (Death Cross)**
   Đường MACD cắt xuống dưới đường Signal — xác nhận momentum ngắn hạn đã yếu hơn momentum dài hạn, tín hiệu giảm được xác nhận.

3. **Giá phá vỡ và đóng cửa dưới MA**
   Nến hiện tại phá vỡ đường MA từ trên xuống và đóng cửa phía dưới — xác nhận giá đã thủng ngưỡng hỗ trợ động, xu hướng giảm được thiết lập.

**Giá vào:** Tiệm cận đường MA (bán gần vùng kháng cự động, rủi ro thấp).

**Thoát lệnh SHORT — bất kỳ 1 trong 4 điều kiện:**

| Điều kiện | Ý nghĩa |
|-----------|---------|
| Giá đóng cửa trên MA | Giá đã phá vỡ kháng cự động — xu hướng giảm thất bại |
| MA chuyển sang tăng (xanh dương/xanh lá) | Đường MA đang dốc lên — xu hướng giảm đang mất đà |
| MACD-Signal chuyển sang tăng | Momentum tổng thể đang đảo chiều lên |
| MACD xanh dương + MA cam | Phân kỳ tăng: momentum ngắn hạn tăng trong khi MA vẫn giảm nhẹ — cảnh báo sớm đảo chiều |

---

### Ưu điểm của chiến lược

- **3 lớp xác nhận** giảm thiểu tín hiệu giả so với dùng đơn lẻ từng chỉ báo
- **Giá vào tiệm cận MA** — tối ưu điểm vào, SL tự nhiên ngay dưới/trên MA
- **Exit đa điều kiện** — thoát lệnh sớm khi có dấu hiệu đảo chiều, bảo vệ lợi nhuận
- **Phân kỳ MACD/MA** — phát hiện sớm điểm yếu của xu hướng trước khi giá đảo chiều hẳn

### Tham số chính

| Tham số | Mặc định | Mô tả |
|---------|----------|-------|
| `bb_length` | 50 | Chu kỳ đường MA cơ sở |
| `macd_fast` | 12 | MACD fast period |
| `macd_slow` | 26 | MACD slow period |
| `macd_signal_length` | 500 | Signal smoothing (dài → ít nhiễu) |
| `timeframe` | 5m | Khung thời gian |

### Tham khảo
- Mã nguồn chiến lược: `src/strategies/sma_macd_cross.py`
- Mã nguồn MACD custom: `docs/custom_macd_pinescript.md`
- Mã nguồn SMA custom: `docs/custom_sma_pinescript.md`
