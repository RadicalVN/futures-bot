# Kế hoạch Triển khai (Implementation Plan)

## Tầm nhìn Hệ thống (System Vision)
Phát triển từ một **Single Trading Script** thành một **Nền tảng Quản lý Bot (Bot Management Platform)**, cho phép khởi tạo, quản lý và vận hành song song nhiều cấu hình Bot trên các cặp giao dịch và chiến thuật khác nhau.

---

## Phase 1: Nền tảng Cơ bản (ĐÃ HOÀN THÀNH)
- [x] **Core Engine:** ccxt.async_support + asyncio
- [x] **Dashboard:** FastAPI + uvicorn + WebSockets
- [x] **Database:** SQLite (với SQLAlchemy ORM)
- [x] **Frontend:** Vanilla JS, CSS, Chart.js (Candlestick)
- [x] **Strategy:** MA + MACD

---

## Phase 2: Hệ thống Multi-bot & Marketplace (ĐANG PHÁT TRIỂN)

### Mục tiêu
- Cho phép người dùng cấu hình nhiều bot (ví dụ: Bot A chạy BTCUSDT chiến thuật MA, Bot B chạy ETHUSDT chiến thuật RSI).
- Cung cấp "Chợ chiến thuật" (Strategy Market) trên UI để chọn.
- Quản lý tập trung các tiến trình bot chạy ngầm.

### Kiến trúc mới (V2 Architecture)
1. **Database Schema:**
   - Tạo mới bảng ots: Quản lý danh sách bot (id, 
ame, symbol, strategy_name, params JSON, status).
   - Cập nhật bảng 	rades và positions: Thêm cột ot_id để phân biệt dữ liệu.
2. **Backend Engine:**
   - Xây dựng BotManager: Class trung tâm chịu trách nhiệm quản lý lifecycle (Start/Stop) của các tiến trình bot độc lập (đa luồng asyncio).
   - Tái cấu trúc BotEngine: Đọc cấu hình từ Database thay vì config.yaml.
3. **Frontend UI:**
   - Thêm trang **Market**: Danh sách các loại chiến thuật (chi tiết, biểu đồ minh họa).
   - Thêm trang **Setup Bot**: Form động (dynamic form) để điền thông số tùy theo chiến thuật.
   - Nâng cấp trang **Dashboard**: Hiển thị lưới danh sách "My Bots" với trạng thái PnL từng con.

### Các bước Triển khai
1. **Thiết kế Database:** Cập nhật các Model của SQLAlchemy (models.py).
2. **Refactor Backend:** Tách cấu hình tĩnh ra khỏi config.yaml và đưa vào CSDL. Xây dựng BotManager.
3. **Thiết kế API:** Cung cấp CRUD API cho việc tạo, cấu hình và xóa Bot.
4. **Xây dựng UI:** Thêm các màn hình Setup, Market và nâng cấp Dashboard.
5. **Testing:** Chạy đồng thời 2-3 bot ảo để kiểm tra chống nghẽn mạng Binance.

