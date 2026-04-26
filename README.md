# Binance Futures Trading Bot 🚀

Một Trading Bot tự động chuyên giao dịch trên sàn Binance (USDT-M Perpetual Futures), tích hợp sẵn chiến lược MA + MACD và giao diện Web Dashboard theo dõi Real-time.

## Tính năng chính
- **Cốt lõi:** Sử dụng thư viện ccxt mạnh mẽ, tối ưu hóa cho Async.
- **Chiến lược (Strategy):** Phân tích tín hiệu giao cắt MA (Fast/Slow) và Momentum của MACD.
- **Quản lý rủi ro:** Stop Loss, Take Profit và định tuyến khối lượng (Position Sizing).
- **Web Dashboard:** Giao diện trực quan (FastAPI + JS), hiển thị số dư, trạng thái vị thế và **biểu đồ Nến Nhật** (Real-time).
- **1-Click Run:** Cấu hình tự động cài đặt qua start.bat trên Windows.
- **Containerization:** Sẵn sàng deploy lên VPS với Docker và docker-compose.

## Bắt đầu nhanh (Local Windows)
1. Clone repo này về máy.
2. Mở thư mục 	rading-service và click đúp vào file start.bat.
3. Hệ thống sẽ tự động tải môi trường Python và mở Dashboard tại http://localhost:8000.

*Lưu ý: Mặc định bot chạy ở chế độ Testnet. Để giao dịch thật, hãy thêm BINANCE_API_KEY và BINANCE_API_SECRET vào file .env.*

## Tài liệu (Docs)
- [Kế hoạch & Cấu trúc (Plan)](docs/plan.md)
- [Lịch sử Cập nhật (Changelog)](docs/history.md)
- [Tính năng & Bố cục UI V2 (Features)](docs/v2_features.md)
