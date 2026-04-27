# Chiến Lược Giao Dịch Dựa Trên Custom SMA

Tài liệu này mô tả chi tiết 3 chiến lược giao dịch được xây dựng dựa trên chỉ báo Custom SMA (ittuantruong),
sử dụng hai trọng số **% Độ Dốc (Slope)** và **% Gia Tốc (Momentum)** để tối ưu điểm vào/ra lệnh.

Tham khảo thêm về cơ sở chỉ báo: [`docs/custom_sma_integration.md`](./custom_sma_integration.md)

---

## Nền tảng chung: Cơ chế Phân Tích Gia Tốc (Momentum Color System)

Mỗi node trên đường TVT-MA-Cross được tô màu thể hiện **cường độ và chiều hướng** của gia tốc SMA:

| Màu | Tên biến | Ý nghĩa |
|---|---|---|
| 🔵 Xanh dương | `blue` | Đang tăng tốc LÊN mạnh (động lực tăng nguyên chất) |
| 🟣 Tím | `purple` | Đảo chiều tăng / giảm (bước ngoặt) |
| 🟠 Cam | `orange` | Đà tăng đang hãm lại (tăng chậm dần) |
| 🟡 Vàng | `yellow` | Đứng yên / sideway |
| 🔴 Đỏ | `red` | Đang tăng tốc XUỐNG mạnh |
| 🟢 Xanh lá | `green` | Đà giảm đang hãm lại (giảm chậm dần) |

---

## Chiến Lược 1: Đánh Thuận Xu Hướng + Thoát Sớm (Early Exit)

**File**: `src/strategies/sma_trend_early_exit.py`  
**Tên engine**: `sma_trend_early_exit`

### Ý tưởng cốt lõi
Vào lệnh khi Trend vừa đảo chiều **VÀ** gia tốc đang mạnh, nhưng **không chờ Trend đổi màu mới thoát** — thay vào đó thoát ngay khi gia tốc bắt đầu suy yếu để bảo toàn lợi nhuận.

### Điều kiện vào lệnh (Entry)
- Trend vừa đảo: `-1 → +1` (cho LONG) hoặc `+1 → -1` (cho SHORT)
- Momentum đang MẠNH: node màu **blue** hoặc **purple**
- `|slope_pct| ≥ min_slope_pct` (lọc tín hiệu khi thị trường đi quá nhẹ)

### Điều kiện thoát lệnh (Exit — Ưu tiên)
| Trường hợp | Hành động |
|---|---|
| Momentum chuyển sang **orange/yellow/green** (đà đang hãm) | Đóng lệnh sớm → Bảo toàn lợi nhuận |
| Trend đảo chiều ngược lại | Đóng lệnh bình thường |

### Tham số cấu hình
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `fast_len` | 1 | Chu kỳ SMA nhanh |
| `slow_len` | 5 | Chu kỳ SMA chậm |
| `len_c` | 200 | Chu kỳ làm mượt tổng hợp |
| `factor` | 0.05 | Hệ số nhiễu đảo chiều Trend |
| `bb_length` | 50 | Chu kỳ SMA Bollinger cơ sở |
| `min_slope_pct` | 0.0 | Ngưỡng độ dốc tối thiểu (%) |

### Phù hợp với
- Thị trường có xu hướng rõ ràng, sóng đơn mạnh
- Người muốn chốt lời nhanh, không để lại quá nhiều lợi nhuận trên bàn

---

## Chiến Lược 2: Bắt Đáy Sóng Hồi (Pullback)

**File**: `src/strategies/sma_pullback.py`  
**Tên engine**: `sma_pullback`

### Ý tưởng cốt lõi
Không vào lệnh ngay khi Trend đảo chiều (tránh mua đuổi đỉnh ngắn hạn). Thay vào đó, **đợi giá hồi lại** (momentum yếu đi) rồi khi **gia tốc bật mạnh trở lại mới vào** — mua được giá tốt hơn, rủi ro thấp hơn so với Chiến lược 1.

### Quy trình 3 bước
```
[Bước 1] Xác nhận Trend đang rõ ràng (Xanh hoặc Đỏ)
[Bước 2] Chờ pha hồi: Momentum xuống orange/yellow/green liên tục ≥ N nến (pullback_confirm_bars)
[Bước 3] Trigger: Momentum bật lên blue/purple (LONG) hoặc xuống red (SHORT) → Vào lệnh
```

### Điều kiện vào lệnh LONG (Pullback Buy)
- `current_trend == 1` (Trend đang Tăng)
- `N` nến gần nhất có momentum ∈ {orange, yellow, green}
- Nến hiện tại momentum ∈ **{blue, purple}**
- `slope_pct ≥ min_slope_pct`

### Điều kiện thoát lệnh
- Trend đảo về `-1` (Giảm)
- Momentum chuyển sang **red** (tăng tốc xuống mạnh)

### Tham số cấu hình
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `pullback_confirm_bars` | 2 | Số nến tối thiểu trong pha hồi trước khi trigger |
| `min_slope_pct` | 0.0 | Ngưỡng độ dốc tối thiểu khi trigger |
| *(các tham số SMA giống CL1)* | — | — |

### Phù hợp với
- Thị trường có xu hướng kéo dài (trending market)
- Người muốn vào lệnh giá tốt hơn đầu sóng, chấp nhận đôi khi bỏ lỡ sóng đầu

---

## Chiến Lược 3: Chống Nhiễu Sideway (Anti-Whipsaw)

**File**: `src/strategies/sma_anti_sideway.py`  
**Tên engine**: `sma_anti_sideway`

### Ý tưởng cốt lõi
Thị trường sideway (đi ngang) là "máy mài tiền" của bot Trend-following. Chiến lược này dùng `|slope_pct|` làm bộ lọc chính: **nếu SMA đang đi gần như nằm ngang → Bot ngủ đông hoàn toàn**, không ra bất kỳ tín hiệu nào cho dù Trend có đổi màu.

### Cơ chế Bộ lọc Sideway
```
|slope_pct| < sideway_slope_threshold  →  Trạng thái "Ngủ đông 😴"
|slope_pct| ≥ sideway_slope_threshold  →  Hoạt động bình thường
```

### Điều kiện vào lệnh
- **Không trong trạng thái sideway** (`|slope_pct|` đủ lớn)
- Trend vừa đảo chiều
- `|momentum_pct| ≥ min_momentum_pct` (confirm thêm)

### Điều kiện thoát lệnh
- `|slope_pct|` thu hẹp về dưới `exit_slope_threshold` → Thị trường bắt đầu tích luỹ → Chốt lời sớm
- Trend đảo chiều ngược lại

### Tham số cấu hình
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `sideway_slope_threshold` | 0.01 | Ngưỡng |% Dốc| để coi là thị trường đang chạy (%) |
| `exit_slope_threshold` | = sideway_threshold | Ngưỡng thu hẹp để thoát lệnh sớm |
| `min_momentum_pct` | 0.0 | Ngưỡng |% Gia tốc| để confirm vào lệnh |
| *(các tham số SMA giống CL1)* | — | — |

### Phù hợp với
- Thị trường chuyển đổi liên tục giữa trending và sideway (TRUMP, altcoin biến động cao)
- Người muốn giảm thiểu số lệnh thua khi thị trường đi ngang

---

## Bots Thử Nghiệm (Seed Data)

6 bots đã được tạo sẵn trong database qua script `scripts/seed_bots.py`:

| Bot Name | Symbol | Strategy | Tham số điều chỉnh |
|---|---|---|---|
| TVT-EarlyExit / BTCUSDT | BTCUSDT | `sma_trend_early_exit` | min_slope_pct=0.002 |
| TVT-EarlyExit / TRUMPUSDT | TRUMPUSDT | `sma_trend_early_exit` | min_slope_pct=0.01 |
| TVT-Pullback / BTCUSDT | BTCUSDT | `sma_pullback` | pullback_confirm_bars=2, min_slope_pct=0.002 |
| TVT-Pullback / TRUMPUSDT | TRUMPUSDT | `sma_pullback` | pullback_confirm_bars=3, min_slope_pct=0.01 |
| TVT-AntiSideway / BTCUSDT | BTCUSDT | `sma_anti_sideway` | sideway_threshold=0.005%, min_mom=0.001% |
| TVT-AntiSideway / TRUMPUSDT | TRUMPUSDT | `sma_anti_sideway` | sideway_threshold=0.015%, min_mom=0.005% |

> **Lưu ý**: TRUMP được cấu hình threshold cao hơn BTC vì altcoin thường có slope/momentum dao động lớn hơn, dễ sinh nhiễu hơn.

### Tái tạo bots (nếu cần reset)
```bash
venv\Scripts\python.exe scripts/seed_bots.py
```

---

## So Sánh 3 Chiến Lược

| Tiêu chí | CL1: Early Exit | CL2: Pullback | CL3: Anti-Sideway |
|---|---|---|---|
| **Số lệnh/ngày** | Nhiều nhất | Ít nhất | Trung bình |
| **Rủi ro/lệnh** | Trung bình | Thấp | Thấp |
| **Tỉ lệ thắng** | Trung bình | Cao (giá vào tốt) | Cao (lọc sideway) |
| **Lợi nhuận/lệnh** | Thấp (thoát sớm) | Cao (bắt điểm tốt) | Trung bình |
| **Phù hợp thị trường** | Trending mạnh | Trending kéo dài | Volatile / Mixed |
| **Nguy hiểm khi** | Sideway (nhiều tín hiệu giả) | Trend thay đổi đột ngột | Threshold chỉnh sai |
