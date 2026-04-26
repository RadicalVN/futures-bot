# Tính năng & Bố cục UI - V2 Multi-Bot Platform

Dưới đây là danh sách toàn bộ các tính năng cốt lõi và bố cục giao diện đã được thiết kế và phát triển cho phiên bản V2 (Chuyển đổi từ Single-bot script sang nền tảng Multi-bot quản lý tập trung).

---

## 1. Bố cục Giao diện Web (UI Layout)
Giao diện được thiết kế theo phong cách tối màu (Dark mode) hiện đại, lấy cảm hứng từ UI của sàn Binance. Gồm 1 Sidebar điều hướng bên trái và vùng Nội dung chính bên phải.

### Tab 1: 🤖 My Bots (Trang Chủ / Quản lý Bot)
Nơi giám sát toàn bộ hoạt động của các Bot.
- **Biểu đồ Nến Nhật (Candlestick Chart):** 
  - Nằm ở trên cùng, kéo dữ liệu nến (OHLCV) trực tiếp từ Binance. 
  - Mặc định tải mã đầu tiên, nhưng có thể bấm "Xem Biểu đồ" ở bất kỳ Bot nào để đổi mã.
- **Bot Grid (Lưới danh sách Bot):**
  - Hiển thị mỗi Bot dưới dạng 1 Thẻ (Card).
  - Tên Bot, Trạng thái (Running / Stopped).
  - Mã giao dịch (Symbols) đang chạy.
  - **Chỉ số:** Lợi nhuận (PnL), Tỷ lệ thắng (Win Rate).
  - **Nút hành động:** Bật/Tắt Bot, Xóa Bot, Xem Biểu đồ.

### Tab 2: 🛒 Strategy Market (Chợ Chiến Thuật)
Nơi cấu hình và khởi tạo các tiến trình Bot mới.
- **Form Khởi Tạo (Setup Form):**
  - **Tên Bot:** Đặt tên gợi nhớ (VD: Bot Lưới BTC).
  - **Tài khoản API:** Chọn tài khoản sẽ được Bot sử dụng để đặt lệnh.
  - **Chiến Thuật:** Chọn từ các thuật toán có sẵn (hiện tại là `MA + MACD Trend Following`).
  - **Mã Giao Dịch (Symbols):** Cho phép nhập nhiều mã cách nhau bằng dấu phẩy (VD: `BTCUSDT, ETHUSDT`) hoặc nhập chữ `ALL` / `AUTO` để bot tự quét toàn thị trường.
  - **Tham Số (JSON):** Cấu hình linh hoạt các thông số như `timeframe`, `leverage` (đòn bẩy), `max_open_positions`.

### Tab 3: ⚙️ Settings (Cài Đặt Hệ Thống)
Nơi quản lý khóa truy cập API (API Keys).
- Hỗ trợ lưu trữ nhiều cấu hình API Keys (Multi-accounts).
- Nhập Tên gợi nhớ, API Key, API Secret.
- Chọn môi trường giao dịch: `Testnet` hoặc `Mainnet`.

---

## 2. Tính năng Lõi (Backend Core Features)

### Kiến Trúc Đa Tiến Trình (Multi-Bot Engine)
- **Bot Manager:** Đóng vai trò là "Tổng Quản Lý". Quét Database mỗi 5 giây để tìm các Bot đang ở trạng thái `running`.
- **Dynamic Spawn:** Tự động tạo và hủy các luồng `asyncio` biệt lập cho từng Bot mà không ảnh hưởng đến Bot khác. Mọi cấu hình đều được tải từ Database (Không dùng file config cứng).

### Quản Lý Rủi Ro & Đặt Lệnh (Order & Risk Management)
- Tự động thiết lập Đòn bẩy (Leverage) và Chế độ Margin (Isolated/Cross) theo cấu hình Bot.
- Tự động tính toán khối lượng lệnh (Position Sizing) tùy theo số dư (Balance) hiện tại.
- Tự động ngăn chặn việc mở lệnh vượt quá giới hạn vị thế (Max Open Positions).

### Chế Độ Quét Thị Trường (Market Scanner)
Hỗ trợ 3 chế độ vận hành:
1. **Custom List:** Chạy trên danh sách cố định (VD: `BTCUSDT, ETHUSDT`).
2. **AUTO:** Tự động gọi API Binance để lọc ra Top các đồng coin có Volume lớn nhất trong 24h để giao dịch.
3. **ALL:** Tự động tải danh sách toàn bộ mã Futures khả dụng và chia nhỏ (chunk) thành từng cụm xử lý để tránh vi phạm Rate Limit của sàn.

### Cơ Sở Dữ Liệu "SaaS-Ready" (SQLite / SQLAlchemy)
- Bảng `ExchangeAccount`: Quản lý bảo mật nhiều API Keys độc lập.
- Bảng `Bot`: Lưu cấu hình và tham số vận hành. Hỗ trợ Soft Delete (Xóa mềm - ẩn khỏi UI nhưng không làm mất dữ liệu PnL).
- Bảng `Trade` & `Signal`: Phân bổ lệnh và tín hiệu gắn với `bot_id` riêng biệt. Tự động cộng/trừ PnL vào bảng Bot.
- Bảng `BotEvent`: Lưu log sự kiện để dễ dàng debug.

### Chuẩn Hóa API (FastAPI RESTful)
- Toàn bộ backend giao tiếp với UI thông qua API độc lập, dễ dàng nâng cấp hoặc viết Mobile App sau này. Mở đường cho kiến trúc Microservices.
