# Kế hoạch Triển khai (Implementation Plan)

## Mục tiêu
Xây dựng một **Futures Trading Bot** chạy trên Binance (USDT-M Perpetual Futures), sử dụng tín hiệu từ MA và MACD. Có kèm theo Web Dashboard để theo dõi real-time.

## Kiến trúc (Architecture)
- **Core Engine:** ccxt.async_support + syncio
- **Dashboard:** FastAPI + uvicorn + WebSockets
- **Database:** SQLite (với SQLAlchemy ORM)
- **Frontend:** Vanilla JS, CSS, Chart.js (với Plugin Candlestick)

## Cấu trúc thư mục
- src/core/: Quản lý sàn, đặt lệnh, rủi ro.
- src/strategies/: Logic thuật toán giao dịch (MA + MACD).
- src/data/: Tính toán chỉ báo kỹ thuật (Indicators).
- src/database/: Các model dữ liệu.
- src/dashboard/: API Server và giao diện Web tĩnh.

## Triển khai VPS
Dự án đã có sẵn Dockerfile và docker-compose.yml. Chỉ cần:
`ash
docker-compose up -d --build
`
