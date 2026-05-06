# Trading Platform Development Guidelines (v1.0)

> Tài liệu này là **luật bất thành văn** của dự án. Mọi contributor (người và AI) đều phải tuân thủ.

---

## 1. Triết lý Thiết kế (Design Philosophy)

Hệ thống được thiết kế theo mô hình **Modular Monolith**, sẵn sàng chuyển đổi sang Microservices.

| Nguyên tắc | Mô tả |
|---|---|
| **Core-Centric** | Các logic dùng chung, hạ tầng (DB, Security, Logging) nằm ở `core`. |
| **App-Isolation** | Các nghiệp vụ (Trading, Monitoring, Advisor) nằm ở `apps`. Mỗi app phải hoạt động độc lập (Bounded Context). |
| **Language-Agnostic Mindset** | Code phải tường minh đến mức một lập trình viên Java/C# nhìn vào cũng hiểu được luồng dữ liệu mà không cần biết sâu về Python "Magic". |

---

## 2. Quy tắc Kiến trúc (Architectural Rules)

### 2.1. Cấm gọi chéo (No Cross-App Imports)

> ❌ **TUYỆT ĐỐI CẤM**: `apps.A` import trực tiếp từ `apps.B`.

**Giải pháp thay thế:**
- Nếu cần **dữ liệu** từ App khác → truy vấn qua **Database**.
- Nếu cần **phản ứng theo sự kiện** → lắng nghe **Event từ Redis**.
- Nếu là **logic tính toán dùng chung** → đưa vào `core`.

```
# ❌ SAI
from apps.trading import some_function

# ✅ ĐÚNG
from core.shared_logic import some_function
# hoặc query DB / subscribe Redis event
```

### 2.2. Giao tiếp qua Dữ liệu (Data-Driven Communication)

- **PostgreSQL** → Source of Truth cho các dữ liệu bền vững.
- **Redis** → Real-time state và Message Broker.
- Mọi App phải có khả năng **khởi động lại (Stateless)** mà không mất đi context quan trọng của lệnh.

---

## 3. Tiêu chuẩn Coding (Coding Standards)

### 3.1. Tính tường minh (Explicit is better than Implicit)

**Type Hinting: Bắt buộc 100%** cho tham số đầu vào và kiểu trả về của hàm.

```python
# ❌ SAI
def calculate_position_size(balance, risk_pct):
    ...

# ✅ ĐÚNG
def calculate_position_size(balance: float, risk_pct: float) -> float:
    ...
```

**Pydantic Models:** Luôn sử dụng Pydantic để validate dữ liệu đầu vào từ API hoặc Config. Tránh dùng `dict` thuần túy.

```python
# ❌ SAI
def process_order(order: dict):
    price = order["price"]

# ✅ ĐÚNG
class OrderRequest(BaseModel):
    price: float
    quantity: float
    symbol: str

def process_order(order: OrderRequest) -> OrderResult:
    ...
```

**Docstring:** Bắt buộc theo **Google style** cho mọi hàm public.

```python
def calculate_position_size(balance: float, risk_pct: float) -> float:
    """Tính kích thước vị thế dựa trên số dư và mức rủi ro.

    Args:
        balance: Số dư tài khoản hiện tại (USDT).
        risk_pct: Phần trăm rủi ro cho phép (0.0 - 1.0).

    Returns:
        Kích thước vị thế tính bằng USDT.

    Raises:
        ValueError: Nếu risk_pct nằm ngoài khoảng [0, 1].
    """
```

### 3.2. Cấu trúc hàm

- Mỗi hàm chỉ làm **một việc** (Single Responsibility).
- Hàm **không được quá 50 dòng** code. Nếu dài hơn, hãy chia nhỏ thành các sub-functions.

---

## 4. Background Jobs & Concurrency

### 4.1. Scheduler Discipline

- Sử dụng bộ khung `core.scheduler` (APScheduler/TaskIQ).
- Mọi tác vụ nền (Exit Monitor, Data Sync) phải được **đăng ký tập trung** tại đây.
- **Idempotency:** Một job chạy lại nhiều lần không được gây ra sai lệch dữ liệu (ví dụ: không được đặt 2 lệnh trùng nhau).

```python
# ✅ Kiểm tra idempotency trước khi thực thi
async def sync_open_orders(bot_id: int) -> None:
    existing = await db.get_open_order(bot_id)
    if existing:
        return  # Đã tồn tại, bỏ qua
    await db.create_order(...)
```

### 4.2. Asyncio First

- Mọi thao tác I/O (Database, API Call, Redis) **bắt buộc dùng `async/await`**.
- **Không sử dụng** các thư viện blocking (như `requests`) trong luồng chính của bot.

```python
# ❌ SAI — blocking call
import requests
response = requests.get(url)

# ✅ ĐÚNG — non-blocking
import httpx
async with httpx.AsyncClient() as client:
    response = await client.get(url)
```

---

## 5. Bảo mật & Tin cậy (Security & Resilience)

### 5.1. Quản lý bí mật

> ❌ **KHÔNG** lưu API Key/Secret dạng plain text ở bất kỳ đâu trong code.

- Bắt buộc decrypt thông qua `core.security.VaultService` khi runtime.
- File `.env` chỉ chứa các **config hạ tầng** (DB URL, Encryption Key) — không chứa secret của exchange.

```python
# ❌ SAI
api_key = "abc123plaintext"

# ✅ ĐÚNG
from core.security import VaultService
api_key = await VaultService.decrypt(bot.encrypted_api_key)
```

### 5.2. Xử lý lỗi (Error Handling)

Sử dụng `try-except` có chọn lọc. **Luôn log đầy đủ stacktrace.**

| Mức độ | Điều kiện | Hành động |
|---|---|---|
| `CRITICAL` | Lỗi API Binance, cháy tài khoản | Bắn Alert ngay lập tức |
| `WARNING` | Lỗi mạng tạm thời, Rate limit | Ghi log và tiếp tục |
| `ERROR` | Lỗi logic nghiệp vụ | Ghi log, dừng tác vụ hiện tại |

```python
# ✅ Mẫu xử lý lỗi chuẩn
try:
    result = await exchange.place_order(order)
except BinanceAPIException as e:
    logger.critical("Binance API error", exc_info=True, extra={"bot_id": bot_id})
    await alert_service.send_critical(f"Bot {bot_id}: {e}")
    raise
except NetworkException as e:
    logger.warning("Temporary network error, retrying...", exc_info=True)
    # retry logic
```

---

## 6. Quy trình làm việc với Kiro AI (AI Instruction — Self-Check)

Mỗi khi thực hiện một task, AI **bắt buộc** tự kiểm tra các checkpoint sau trước khi viết code:

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI SELF-CHECK CHECKLIST                      │
├─────┬───────────────────────────────────────────────────────────┤
│  1  │ Logic này thuộc về `core` hay `apps`?                     │
│  2  │ Đã thêm Type Hinting và Docstring (Google style) chưa?    │
│  3  │ Nếu thay đổi trạng thái bot, dữ liệu đã được persist      │
│     │ vào DB chưa?                                              │
│  4  │ Có gây block event loop (blocking code) không?            │
│  5  │ Các file legacy liên quan đã được xóa/refactor sạch chưa? │
└─────┴───────────────────────────────────────────────────────────┘
```

> **Note for AI:** Be a strict architect. If a request violates the **"No Cross-App Imports"** rule, suggest a Database/Redis solution instead of just coding it.

---

## 7. Quy trình Triển khai của AI (AI Execution Protocol)

> Để đảm bảo tính kiểm soát, AI **KHÔNG ĐƯỢC** tự ý viết code ngay lập tức. Phải tuân thủ quy trình 3 bước bắt buộc.

### Bước 1: Khảo sát & Phân tích (Discovery)

- AI **phải đọc** các file liên quan trong module mục tiêu trước khi làm bất cứ điều gì.
- Xác định các **điểm ảnh hưởng (Side effects)** đến các module khác.

### Bước 2: Đề xuất Giải pháp (Technical Design Proposal)

Trước khi viết code, AI phải trình bày một bản kế hoạch ngắn gọn bao gồm:

| Mục | Nội dung cần trình bày |
|---|---|
| **Mục tiêu** | Task này giải quyết vấn đề gì? |
| **Thay đổi cấu trúc** | Sẽ thêm/sửa những file nào? Nằm ở `/core` hay `/apps`? |
| **Logic chính** | Mô tả thuật toán hoặc flowchart xử lý (nếu phức tạp). |
| **Dependency** | Có cài thêm thư viện ngoài nào không? *(Phải được Tech Lead đồng ý)* |

> **Dừng lại chờ xác nhận:** Kết thúc đề xuất bằng câu:
> *"Tôi đã có kế hoạch, bạn có đồng ý với hướng tiếp cận này để tôi bắt đầu implement không?"*

### Bước 3: Thực thi có kiểm soát (Implementation)

- Chỉ thực thi **sau khi nhận được xác nhận (Confirm)** từ người dùng.
- **Atomic Changes:** Thực hiện thay đổi theo từng phần nhỏ. Không sửa quá nhiều file cùng lúc nếu không liên quan trực tiếp đến Task.

```
┌──────────────────────────────────────────────────────────┐
│              AI EXECUTION FLOW                           │
│                                                          │
│   [Task nhận được]                                       │
│        │                                                 │
│        ▼                                                 │
│   Bước 1: Đọc file liên quan → Xác định side effects    │
│        │                                                 │
│        ▼                                                 │
│   Bước 2: Trình bày kế hoạch → Chờ xác nhận ──► STOP   │
│        │ (confirmed)                                     │
│        ▼                                                 │
│   Bước 3: Implement từng phần nhỏ → Verify              │
└──────────────────────────────────────────────────────────┘
```

---

## 8. Kỷ luật "Không tự do" (Strict Implementation Rules)

### 8.1. Cấm tự ý thay đổi Logic lõi (No Stealth Changes)

> ❌ AI không được tự ý **refactor** các đoạn code cũ không liên quan đến Task hiện tại trừ khi được yêu cầu.

Nếu phát hiện code cũ có vấn đề (Code smell), AI phải **báo cáo/gợi ý** thay vì tự ý sửa đè.

```python
# ✅ ĐÚNG — Báo cáo và hỏi
# "Tôi nhận thấy hàm X trong file Y có thể gây memory leak.
#  Bạn có muốn tôi fix luôn trong task này không?"

# ❌ SAI — Tự ý sửa mà không thông báo
```

### 8.2. Tuân thủ Pattern hiện có (Mimic Existing Style)

AI phải **bắt chước (mimic)** coding style của các file hiện có trong cùng module:
- Cách đặt tên biến, hàm, class.
- Cách tổ chức và thứ tự các thành phần trong class.
- Cách import và cấu trúc file.

> Mục tiêu: Người đọc không thể phân biệt đâu là code do AI viết, đâu là code do human viết.

### 8.3. Verification (Kiểm chứng)

Mỗi khi viết xong một function/module, AI **bắt buộc** cung cấp một trong hai:

- **Example Usage** — đoạn code minh họa cách dùng thực tế.
- **Unit Test đơn giản** — chứng minh code chạy đúng như thiết kế.

```python
# Ví dụ: Sau khi viết hàm calculate_position_size()
# AI phải cung cấp:

# --- Example Usage ---
# balance = 1000.0
# risk_pct = 0.02
# result = calculate_position_size(balance, risk_pct)
# assert result == 20.0, f"Expected 20.0, got {result}"
# print(f"Position size: {result} USDT")  # Position size: 20.0 USDT
```

---

## 9. Tóm tắt nhanh (Quick Reference)

| Việc cần làm | ✅ Làm | ❌ Không làm |
|---|---|---|
| Chia sẻ logic giữa apps | Đưa vào `core` | Import chéo giữa `apps` |
| Lưu trạng thái | PostgreSQL / Redis | In-memory variable |
| Gọi API ngoài | `async httpx` | `requests` (blocking) |
| Validate input | Pydantic model | Raw `dict` |
| Lưu API key | Encrypted + VaultService | Plain text |
| Viết hàm | ≤ 50 dòng, 1 nhiệm vụ | Hàm "God" làm mọi thứ |
| Type hint | Bắt buộc 100% | Bỏ qua |
| Nhận task mới | Discovery → Proposal → Confirm → Implement | Code ngay lập tức |
| Phát hiện code smell | Báo cáo, hỏi ý kiến | Tự ý refactor |
| Hoàn thành function | Cung cấp Example Usage / Unit Test | Không có verification |
| Thêm thư viện mới | Xin phép Tech Lead | Tự ý thêm vào requirements |
