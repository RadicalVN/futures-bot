# Chiến lược SMA + MACD Cross (TVT-SMA+MACD)

---

## Phần 1 — Mô tả gốc

### Entry LONG
**Điều kiện 1:** MACD-Signal màu xanh lá/xanh dương
**và Điều kiện 2:** MACD phải đang hoặc đã cắt qua MACD-Signal từ dưới lên
**và Điều kiện 3:** Giá/nến phải cắt qua MA, kết thúc nến giá phải nằm trên MA

→ Giá mua: là giá trung bình của giá cao và gần nhất với giá tại điểm giao nhau gần nhất của sma và đường giá
- độ lệch giá vào lệnh (lưu lại) là giá trị tuyệt đối của giá mua - giá tại điểm giao nhau gần nhất của sma và đường giá.

**Exit LONG (ExitMonitor check):**
- Trường hợp đóng lệnh 1:
  + Điều kiện 1: bắt buộc phải có nến mà giá đóng nến nằm dưới đường MA
  + Điều kiện 2: nếu giá đóng nến của phiên đang xét mà bé hơn tổng của giá tại điểm giao nhau của ma với đường giá + độ lệch giá vào lệnh (không có thì mặc định 0)

  => thoả 2 điều kiện thì đóng lệnh với giá đóng lệnh là giá trung bình của giá thấp và gần nhất
  với giá tại điểm giao nhau gần nhất của sma và đường giá.

- Trường hợp đóng lệnh 2: MACD-Signal chuyển đỏ/cam → đóng ngay
- Trường hợp đóng lệnh 3: có phiên MACD đỏ, MA xanh lá sau điểm vào lệnh → đóng ngay

---

### Entry SHORT
**Điều kiện 1:** MACD-Signal màu cam/đỏ
**và Điều kiện 2:** MACD phải đang hoặc đã cắt qua MACD-Signal từ trên xuống
**và Điều kiện 3:** Giá/nến phải cắt qua MA, kết thúc nến giá phải nằm dưới MA

→ Giá bán: là giá trung bình của giá thấp và gần nhất với giá tại điểm giao nhau gần nhất của sma và đường giá
- độ lệch giá vào lệnh (lưu lại) là giá trị tuyệt đối của giá bán - giá tại điểm giao nhau gần nhất của sma và đường giá.

**Exit SHORT (ExitMonitor check):**
- Trường hợp đóng lệnh 1:
  + Điều kiện 1: bắt buộc phải có nến mà giá đóng nến nằm trên đường MA
  + Điều kiện 2: nếu giá đóng nến của phiên đang xét mà lớn hơn tổng của giá tại điểm giao nhau của ma với đường giá + độ lệch giá vào lệnh (không có thì mặc định 0)

  => thoả 2 điều kiện thì đóng lệnh với giá đóng lệnh là giá trung bình của giá cao và gần nhất
  với giá tại điểm giao nhau gần nhất của sma và đường giá.

- Trường hợp đóng lệnh 2: MACD-Signal chuyển xanh lá/xanh dương → đóng ngay
- Trường hợp đóng lệnh 3: có phiên MACD xanh dương, MA cam sau điểm vào lệnh → đóng ngay

---

## Phần 2 — Mô tả theo ngôn ngữ trader

### Tổng quan

Chiến lược kết hợp **đường MA (Moving Average)** và **MACD custom** để xác nhận điểm vào lệnh với 3 lớp xác nhận độc lập. Điểm đặc biệt: giá vào lệnh được tính toán tiệm cận điểm giao nhau của giá và MA — tức là vào lệnh sát vùng hỗ trợ/kháng cự động, tối ưu Risk/Reward. Chiến lược lưu lại **độ lệch giá vào** để dùng làm ngưỡng xác nhận khi thoát lệnh.

---

### Entry LONG (Mua)

**Bối cảnh:** Momentum đang tích cực (MACD-Signal xanh), MACD đã vượt lên trên Signal, và giá vừa phá vỡ MA từ dưới lên.

**3 điều kiện phải đồng thời thỏa:**

| # | Điều kiện | Ý nghĩa |
|---|-----------|---------|
| 1 | MACD-Signal đang màu **xanh lá hoặc xanh dương** | Momentum tổng thể đang tích cực — lực mua đang chiếm ưu thế |
| 2 | MACD **đang hoặc đã** cắt lên trên Signal (MACD ≥ Signal) | Golden cross đã xảy ra — momentum ngắn hạn mạnh hơn dài hạn |
| 3 | Nến hiện tại **đóng cửa trên MA** (giá cắt qua MA từ dưới lên) | Giá phá vỡ kháng cự động — xu hướng tăng được xác nhận |

**Giá vào lệnh:**
- Lấy trung bình của `high` nến hiện tại và giá tại điểm giao nhau gần nhất của MA với đường giá
- Lưu lại **độ lệch** = `|giá vào - giá giao nhau MA|` để dùng cho điều kiện thoát

**Thoát lệnh LONG — theo thứ tự ưu tiên:**

| Trường hợp | Điều kiện | Hành động |
|-----------|-----------|-----------|
| **TH1** (có chọn lọc) | Giá đóng cửa **dưới MA** VÀ giá đóng cửa < (giá giao nhau MA + độ lệch) | Đóng với giá = trung bình `low` và giá giao nhau MA gần nhất |
| **TH2** (ngay lập tức) | MACD-Signal chuyển sang **đỏ hoặc cam** | Đóng ngay theo giá thị trường |
| **TH3** (ngay lập tức) | MACD màu **đỏ** trong khi MA màu **xanh lá** | Đóng ngay — phân kỳ giảm: momentum ngắn hạn suy yếu trước MA |

> **Lưu ý TH1:** Yêu cầu cả 2 điều kiện — giá dưới MA *và* chưa vượt quá ngưỡng độ lệch. Điều này tránh đóng lệnh quá sớm khi giá chỉ chạm MA rồi bật lại.

---

### Entry SHORT (Bán)

**Bối cảnh:** Momentum đang tiêu cực (MACD-Signal đỏ/cam), MACD đã cắt xuống dưới Signal, và giá vừa phá vỡ MA từ trên xuống.

**3 điều kiện phải đồng thời thỏa:**

| # | Điều kiện | Ý nghĩa |
|---|-----------|---------|
| 1 | MACD-Signal đang màu **cam hoặc đỏ** | Momentum tổng thể đang tiêu cực — lực bán đang chiếm ưu thế |
| 2 | MACD **đang hoặc đã** cắt xuống dưới Signal (MACD ≤ Signal) | Death cross đã xảy ra — momentum ngắn hạn yếu hơn dài hạn |
| 3 | Nến hiện tại **đóng cửa dưới MA** (giá cắt qua MA từ trên xuống) | Giá phá vỡ hỗ trợ động — xu hướng giảm được xác nhận |

**Giá vào lệnh:**
- Lấy trung bình của `low` nến hiện tại và giá tại điểm giao nhau gần nhất của MA với đường giá
- Lưu lại **độ lệch** = `|giá vào - giá giao nhau MA|` để dùng cho điều kiện thoát

**Thoát lệnh SHORT — theo thứ tự ưu tiên:**

| Trường hợp | Điều kiện | Hành động |
|-----------|-----------|-----------|
| **TH1** (có chọn lọc) | Giá đóng cửa **trên MA** VÀ giá đóng cửa > (giá giao nhau MA + độ lệch) | Đóng với giá = trung bình `high` và giá giao nhau MA gần nhất |
| **TH2** (ngay lập tức) | MACD-Signal chuyển sang **xanh lá hoặc xanh dương** | Đóng ngay theo giá thị trường |
| **TH3** (ngay lập tức) | MACD màu **xanh dương** trong khi MA màu **cam** | Đóng ngay — phân kỳ tăng: momentum ngắn hạn phục hồi trước MA |

> **Lưu ý TH1:** Yêu cầu cả 2 điều kiện — giá trên MA *và* đã vượt quá ngưỡng độ lệch. Tránh đóng lệnh quá sớm khi giá chỉ chạm MA rồi tiếp tục giảm.

---

### Điểm giao nhau MA (MA Crossover Price)

Điểm giao nhau gần nhất của MA với đường giá là giá tại nến mà giá đóng cửa vừa cắt qua MA (nến entry hoặc nến gần nhất trước đó có sự giao nhau). Trong thực tế tính toán:

- **LONG**: `ma_cross_price = ma_curr` (giá MA tại nến entry — điểm giá vừa cắt lên)
- **SHORT**: `ma_cross_price = ma_curr` (giá MA tại nến entry — điểm giá vừa cắt xuống)
- **Giá vào LONG** = `(high_curr + ma_cross_price) / 2`
- **Giá vào SHORT** = `(low_curr + ma_cross_price) / 2`
- **Độ lệch** = `|giá vào - ma_cross_price|`

---

### Màu sắc chỉ báo (Color Coding)

Cả MA và MACD-Signal đều dùng cùng rule màu dựa trên **slope momentum**:

| Màu | Ý nghĩa |
|-----|---------|
| 🔵 Xanh dương | Đang tăng và tăng tốc |
| 🟢 Xanh lá | Đang tăng nhưng giảm tốc |
| 🟠 Cam | Đang giảm nhưng giảm tốc (sắp đảo chiều?) |
| 🔴 Đỏ | Đang giảm và tăng tốc |
| 🟣 Tím | Đảo chiều / trung tính |
| 🟡 Vàng | Không thay đổi |

**Nhóm màu cho logic chiến lược:**
- **Bullish** (tích cực): xanh dương, xanh lá
- **Bearish** (tiêu cực): đỏ, cam

---

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
