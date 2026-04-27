# Tính năng & Bố cục UI - V2 Multi-Bot Platform

Dưới đây là danh sách toàn bộ các tính năng cốt lõi và bố cục giao diện đã được thiết kế và phát triển cho phiên bản V2 (Chuyển đổi từ Single-bot script sang nền tảng Multi-bot quản lý tập trung).

---

## 1. Bố cục Giao diện Web (UI Layout)
Giao diện được thiết kế theo phong cách tối màu (Dark mode) hiện đại, lấy cảm hứng từ UI của sàn Binance. Gồm 1 Sidebar điều hướng bên trái và vùng Nội dung chính bên phải.

### Tab 1: 📊 Tổng Quan (Dashboard)
Hiển thị toàn cảnh tình hình giao dịch:
- **Thống kê:** Tổng lợi nhuận (PnL), số lượng Bot đang chạy.
- **Biểu đồ Nến Nhật (TradingView Style):** 
  - Hiển thị giá và các đường SMA.
  - Tích hợp **khung hiển thị MACD độc lập** nằm bên dưới (Stacked Scales) với biểu đồ MACD Histogram màu Xanh/Đỏ cực chuẩn xác.
- **Lịch sử:** Nhật ký hoạt động của hệ thống (Logs) và các lệnh gần nhất.

### Tab 2: 🤖 Quản lý Bot (My Bots)
Nơi giám sát toàn bộ hoạt động của các Bot.
- Hiển thị mỗi Bot dưới dạng 1 Thẻ (Card) bao gồm Trạng thái, Symbol, PnL, Tỷ lệ thắng.
- **Nút hành động:** Bật/Tắt Bot, Xóa Bot (Soft delete).

### Tab 3: 🛒 Chiến Lược Giao Dịch (Strategies)
Nơi cấu hình và khởi tạo các tiến trình Bot mới.
- Khởi tạo Bot với form động: Tên Bot, Tài khoản API, Chiến Thuật (VD: MA + MACD Trend Following), Symbols, Tham số (JSON).
- Danh sách các chiến lược có sẵn để lựa chọn.

### Tab 4: 📈 Chỉ Báo Kỹ Thuật (Indicators)
Quản lý các chỉ báo hỗ trợ cho **Biểu đồ Nến**:
- Cho phép người dùng bật/tắt hiển thị (Toggle Switch) các chỉ báo như Custom SMA, Custom MACD.
- Thiết kế tách biệt hoàn toàn khái niệm "Chiến lược Bot" (Dùng để trade) và "Chỉ báo biểu đồ" (Dùng để xem).

### Tab 5: ⚙️ Cài Đặt (Settings)
Nơi quản lý khóa truy cập API (API Keys).
- Hỗ trợ lưu trữ nhiều cấu hình API Keys (Multi-accounts).
- Chọn môi trường giao dịch: `Testnet` hoặc `Mainnet`.

---

## 2. Tính năng Lõi (Backend & Frontend Architecture)

### Cấu Trúc Frontend Tiên Tiến (ES6 Modules)
- File monolith JavaScript đã được phân mảnh thành các **ES6 Modules** độc lập (`api.js`, `chart.js`, `bots.js`,...).
- Cô lập các lỗi tiềm ẩn, giúp việc bảo trì hiển thị biểu đồ hay thêm tính năng UI mới trở nên an toàn tuyệt đối.

### Chuẩn Hóa API (FastAPI RESTful + Routers + Pydantic)
- Chuyển đổi kiến trúc sang dạng Router (`/routers/bots.py`, `/routers/accounts.py`...).
- Ứng dụng **Pydantic Schemas (DTO)** để Validation chặt chẽ dữ liệu gửi lên từ giao diện. Báo lỗi 422 ngay nếu cấu trúc JSON không hợp lệ.
- Tự động sinh Swagger Docs cho API.

### Kiến Trúc Đa Tiến Trình (Multi-Bot Engine)
- **Bot Manager:** Đóng vai trò là "Tổng Quản Lý". Quét Database mỗi 5 giây để tìm các Bot đang ở trạng thái `running`.
- **Dynamic Spawn:** Tự động tạo và hủy các luồng `asyncio` biệt lập cho từng Bot mà không ảnh hưởng đến Bot khác. Mọi cấu hình đều được tải từ Database (Không dùng file config cứng).

### Quản Lý Rủi Ro & Đặt Lệnh (Order & Risk Management)
- Tự động thiết lập Đòn bẩy (Leverage) và Chế độ Margin (Isolated/Cross) theo cấu hình Bot.
- Tự động tính toán khối lượng lệnh (Position Sizing) tùy theo số dư (Balance) hiện tại.
- Tự động ngăn chặn việc mở lệnh vượt quá giới hạn vị thế (Max Open Positions).

### Cơ Sở Dữ Liệu "SaaS-Ready" (SQLite / SQLAlchemy)
- Bảng `ExchangeAccount`: Quản lý bảo mật nhiều API Keys độc lập.
- Bảng `Bot`: Lưu cấu hình và tham số vận hành. Hỗ trợ Soft Delete.
- Bảng `Trade` & `Signal`: Phân bổ lệnh và tín hiệu gắn với `bot_id` riêng biệt. Tự động cộng/trừ PnL vào bảng Bot.
- Bảng `BotEvent`: Lưu log sự kiện để dễ dàng debug.
