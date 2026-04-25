# Lịch sử Cập nhật (Update History)

## [1.1.0] - 2026-04-26
### Added
- **UI:** Nâng cấp biểu đồ giá mặc định trên Dashboard sang dạng Nến Nhật (Candlestick) với màu sắc rõ nét và thông số O-H-L-C khi hover.
- **Docs:** Tạo thư mục docs/ và bổ sung tài liệu kiến trúc, lịch sử cập nhật.
### Fixed
- **Network:** Gỡ bỏ thư viện iodns để sửa lỗi Could not contact DNS servers trên Windows khi kết nối với Binance Testnet.

## [1.0.0] - 2026-04-25
### Added
- **Core:** Khởi tạo Trading Engine kết nối Binance qua ccxt.
- **Strategy:** Hoàn thiện thuật toán MA + MACD.
- **Dashboard:** Xây dựng hệ thống backend FastAPI và Web UI tĩnh.
- **Setup:** Thêm script start.bat để cài đặt và chạy nhanh trên Windows (1-click).
- **Deploy:** Chuẩn bị sẵn Docker cấu hình.
### Changed
- Khắc phục các vấn đề tương thích môi trường Python 3.14 (loại bỏ pandas-ta gây lỗi biên dịch trên bản mới).
- Migration toàn bộ dự án vào cấu trúc Git repository chuẩn.
