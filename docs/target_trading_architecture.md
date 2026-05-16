# Architecture Proposal: Target Trading System (Kiến trúc Tương lai)
**Version:** 3.0 (Atomic Data & Resilient Microservices)
**Target:** SaaS Platform, High Scalability, Multi-Asset, Institutional-Grade Reliability

## 1. Executive Summary (Tổng quan)
Kiến trúc Tương lai (Target Architecture) đưa nền tảng chuyển dịch từ công cụ cá nhân sang mô hình **SaaS Multi-tenant**, hỗ trợ hàng ngàn người dùng, đa nền tảng (Crypto, Forex, Stocks). 
Đặc biệt, phiên bản này bổ sung các chốt chặn tiêu chuẩn tài chính khắt khe về **Tính Đúng Đắn (Correctness)** và **Độ Ổn Định (Resilience)**.

## 2. Tiêu Chuẩn "Tính Đúng Đắn & Ổn Định" Toàn Cục

1. **Atomic 1m Data & Resampling:** Market Data Hub không tải các nến timeframe lớn. Mọi dòng dữ liệu chảy trong Kafka đều là Tick data hoặc nến 1m nguyên tử.
2. **Data Integrity Pipeline:** Dữ liệu trước khi vào Signal Service bị lọc rác, check gap, check outlier tại một node kiểm định độc lập.
3. **Stateless Workers:** Strategy Worker farm có thể bị kill và spawn lại bất kỳ lúc nào mà không làm mất trạng thái quản lý lệnh nhờ đồng bộ Redis State Store.
4. **Global Circuit Breaker:** Ngắt giao dịch toàn hệ thống tự động khi Sàn có sự cố diện rộng.
5. **Universal Session Adapters:** Xử lý logic giờ mở/đóng cửa phức tạp của thị trường tài chính truyền thống (TradFi).

---

## 3. Kiến trúc Đề xuất (Target Event-Driven Architecture)

Giải pháp tách bạch hoàn toàn luồng Market Data và Luồng Execution thông qua Message Broker, kết hợp các Trạm Gác (Guards).

```mermaid
graph TD
    subgraph External Trading Venues
        Binance[Binance / Bybit]
        Forex[Forex: Oanda / MT5]
        Stocks[Stocks: Alpaca / IBKR]
    end

    subgraph Market Data Hub (MDH)
        Adapter[Universal Session Adapters]
        IntegrityGuard[Data Integrity & Gap Detector]
    end

    subgraph High-Throughput Event Bus
        Kafka[(Kafka Streams / Redis PubSub)]
    end

    subgraph Computation & Strategy Layer
        Resampler[Global Timeframe Resampler]
        SignalSvc[Signal & Indicator Service]
        WorkerPool[Stateless Strategy Workers]
        RedisState[(Redis State Sync)]
    end

    subgraph Routing & Risk Management
        RiskMngr[Global Portfolio & Risk Manager]
        Breaker{Circuit Breaker}
        OrderMngr[Order Routing Service]
        Vault[(HashiCorp Vault)]
    end

    %% Flow: Data Collection
    Binance & Forex & Stocks -->|WSS / REST (Tick/1m)| Adapter
    Adapter -->|Session Managed Data| IntegrityGuard
    IntegrityGuard -.->|Block Noise| Null
    IntegrityGuard -->|Clean 1m Data| Kafka
    
    %% Flow: Processing
    Kafka -->|1m Data| Resampler
    Resampler -->|TF 5m, 15m, 1h| SignalSvc
    SignalSvc -->|AnalyzedEvent| Kafka

    %% Flow: Strategy
    Kafka -->|Sub: Events| WorkerPool
    WorkerPool <-->|Sync TP/SL/Trailing| RedisState
    WorkerPool -->|OrderIntent| Kafka

    %% Flow: Execution
    Kafka -->|Sub: OrderIntent| RiskMngr
    RiskMngr -->|Approve| Breaker
    Breaker -->|Status: OK| OrderMngr
    Breaker -.->|Status: HALT| RiskMngr
    
    Vault -.->|Decrypt API Keys on RAM| OrderMngr
    OrderMngr -->|Execute| External Trading Venues
```

---

## 4. Phân Tích Chuyên Sâu Các Lõi Xử Lý Mới

### 4.1. Universal Adapter & Market Data Hub (MDH)
- **Adapter** kết nối WSS lấy dữ liệu Tick hoặc Nến 1 phút. Nhận thức được Session (Đầu phiên Á, Phiên Âu, Phiên Mỹ). Nếu nhận dữ liệu của cổ phiếu sau giờ giao dịch (After-hours) thanh khoản kém, Adapter sẽ tag cảnh báo.
- **Integrity Guard:** Một Microservice nằm trong MDH. Nếu phát hiện Data Lags từ sàn Binance (Websocket bị nghẽn), nó lập tức drop bản tin hoặc gắn cờ `IS_STALE` để các Bot phía sau hủy phân tích, bảo vệ tiền của khách hàng.

### 4.2. Khối Tính Toán Tập Trung (Computation Layer)
- Mọi dữ liệu timeframe (15m, 4h) do **Global Resampler** đóng gói từ dòng chảy 1m, bảo đảm tính thống nhất cho toàn bộ hàng ngàn Bot.
- **Signal Service** tính toán Indicator 1 lần duy nhất cho mỗi symbol, giúp tiết kiệm hàng ngàn đô la chi phí CPU server.

### 4.3. Stateless Workers & Redis State Sync
- Chống thảm họa (Disaster Recovery): Khi Kubernetes thay thế Pod Strategy Worker bị lỗi, Worker mới spawn lên lập tức đọc **Redis State Sync** để biết Bot A đang giữ vị thế mua BTC, giá SL là bao nhiêu, và tiếp tục trailing stop mượt mà. Không có độ trễ, không mất lệnh.

### 4.4. Risk Manager & Global Circuit Breaker
- Khác với kiến trúc Bước đệm (Breaker nằm trên từng Bot), Kiến trúc Tương lai sở hữu **Global Circuit Breaker**.
- Giám sát toàn cục: Nếu nhận thấy tỷ lệ lỗi (Error Rate) khi gọi API lên Binance tăng vọt qua 15%, Circuit Breaker sẽ gạt cầu dao, chặn toàn bộ 10,000 lệnh Mở Mới của khách hàng, đẩy thông báo "Binance API Degraded" lên Mobile App/Web Dashboard. Chỉ cho phép lệnh Chốt Lời / Cắt Lỗ xuyên qua để bảo vệ danh mục.
