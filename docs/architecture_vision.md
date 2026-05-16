# Bản Đồ Tiến Hoá Kiến Trúc Hệ Thống Giao Dịch (Architecture Evolution Vision)
**Version:** 2.0 (Bản nâng cấp Tiêu chuẩn Tính Đúng Đắn & Sự Ổn Định)
**Context:** Chuyển đổi từ Monolithic Script sang Multi-tenant SaaS đa tài sản.

Tài liệu này định nghĩa 2 phiên bản kiến trúc định hướng cho hệ thống:
1. **Kiến trúc Tương lai (Target Architecture)**: Dành cho hệ thống SaaS lớn.
2. **Kiến trúc Bước đệm (Intermediate Architecture)**: Tối ưu cho giai đoạn R&D chiến lược hiện tại.

---

## 1. Tại sao cần 2 giai đoạn?
Mục tiêu cuối cùng là nền tảng SaaS Multi-tenant, giao dịch trên nhiều sàn (Binance, OKX, Broker), đa tài sản (Crypto, Stock, FX), với hàng ngàn Bot chạy đồng thời. Tuy nhiên, việc xây dựng kiến trúc microservices (Kafka, k8s) ngay từ đầu gây lãng phí nguồn lực.

Trong giai đoạn hiện tại (1 user, vài coin, R&D chiến lược), ưu tiên số 1 là **Tính Đúng Đắn Tuyệt Đối (Correctness)** và **Sự Ổn Định (Stability)**.
Chúng ta áp dụng **Kiến trúc Bước đệm (Modular Monolith)** - cô lập bằng Interface thay vì Network Boundaries, tích hợp chặt chẽ các chốt chặn bảo vệ dữ liệu để đảm bảo Backtest = Live 100%.

---

## 2. Tiêu chuẩn Kiến trúc Bất biến (Core Architectural Standards)
Bất kể ở giai đoạn Bước Đệm hay Tương Lai, kiến trúc phải tuân thủ nghiêm ngặt 5 nguyên tắc sau để đạt tiêu chuẩn tổ chức tài chính:

1. **Dữ liệu Nguyên tử (Atomic 1m - Single Source of Truth):** 
   - Hệ thống (Data Layer) chỉ được phép lấy nến `1m` từ các Sàn. Mọi khung thời gian khác (5m, 15m, 1h, 1d) bắt buộc phải được sinh ra từ module `Resampler` in-memory.
   - Tránh tình trạng nến 5m lệch giá mở/đóng so với tập hợp 5 nến 1m, bảo đảm tính nhất quán tuyệt đối giữa Backtest Tick-level và Live.

2. **Data Integrity Guard (Trạm Gác Dữ Liệu):** 
   - Một tầng Middleware nằm giữa Data Layer và Strategy. Tầng này sẽ quét mảng nến (OHLCV). 
   - **Quyền hạn:** Block action của Bot (hủy bỏ phân tích kỳ đó) nếu phát hiện: Gap dữ liệu (mất nến), không đủ nến Warmup (ví dụ EMA200 nhưng chỉ có 150 nến), hoặc phát hiện giá dị thường (Spike/Outliers do lỗi API Sàn).

3. **Stateless Strategy Sync (Đồng bộ Trạng thái Không Lỗi):**
   - Strategy không bao giờ giữ trạng thái quản lý lệnh (SL, TP, Trailing Stop) in-memory.
   - Mọi thay đổi về trạng thái lệnh phải được đồng bộ tức thời (Persist) vào Database trước khi thực thi. Nếu Server Crash, hệ thống khởi động lại sẽ tái tạo (Rehydrate) trạng thái chính xác.

4. **Safe Mode & Circuit Breaker (Cầu Dao Tự Động):**
   - Hệ thống có cơ chế Ping/Latency Monitor. Nếu phát hiện trễ mạng (Network Latency > 1000ms) hoặc API Sàn trả lỗi 5xx liên tục, Circuit Breaker tự động `Open`.
   - Khi `Open`: Chặn toàn bộ lệnh Mở mới (Entry), chỉ cho phép lệnh Đóng (Exit/SL/TP). Đồng thời gửi Alert khẩn cấp.

5. **Universal Adapter (Tương thích Đa Thị Trường):**
   - Lớp `IDataAdapter` không chỉ gọi API mà phải nhận diện **Phiên Giao Dịch (Trading Sessions)**. 
   - Phân biệt giờ mở cửa/đóng cửa của Chứng khoán (NYSE), thời gian thanh khoản mỏng của Forex để tạm ngừng Bot, tránh các tín hiệu nhiễu đầu phiên.

---

## 3. So sánh Kiến trúc

| Tiêu chí | Giai đoạn hiện tại (Legacy) | Kiến trúc Bước đệm (Intermediate) | Kiến trúc Tương lai (Target) |
|---|---|---|---|
| **Mô hình** | Monolithic Loop | Modular Monolith (Virtual Event-Driven) | Microservices (Event-Driven) |
| **Data Fetching** | Lấy nến theo Timeframe Bot cấu hình | **Atomic 1m** + In-memory Resampler | **MDS** đẩy nến 1m qua Message Broker |
| **Bảo vệ Dữ liệu** | Không có | **Data Integrity Guard** Middleware | **Integrity Svc** + Anomaly Detection |
| **Quản lý Trạng thái**| State nằm trên RAM | **Stateless Strategy Sync** (DB Persist) | Redis State Store / DB Sync |
| **An toàn Hệ thống** | Chờ Exception văng ra | **Circuit Breaker** chặn Entry | Distributed Circuit Breaker |

## 4. Lộ trình Chuyển đổi (Migration Roadmap)

**Giai đoạn 1: Kiện toàn Tính Đúng Đắn (Bước đệm)**
- Chuyển toàn bộ Data Feeder sang việc chỉ lấy nến 1 phút. Viết class `Resampler`.
- Bổ sung class `DataIntegrityGuard` chặn trước hàm `Strategy.analyze()`.
- Ráp Circuit Breaker vào `OrderExecutionService`.

**Giai đoạn 2: Scale-up Data Layer**
- Khi tài sản mở rộng, đưa DataFeeder ra thành Market Data Service độc lập, đẩy dữ liệu 1m đã qua kiểm định lên Redis PubSub.

**Giai đoạn 3: Phân rã Microservices (Multi-tenant)**
- Đưa mã hóa API Key vào Vault. Triển khai Worker Pool cho Strategy lên Kubernetes. Đưa Risk Manager thành dịch vụ toàn cục.
