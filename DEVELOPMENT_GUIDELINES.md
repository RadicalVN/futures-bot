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
- **Bắt buộc tự Review → Build → Run Check** sau khi implement xong, trước khi báo cáo hoàn thành:

| Bước | Hành động | Công cụ |
|---|---|---|
| **Review** | Đọc lại toàn bộ file đã thay đổi, kiểm tra logic, type hint, docstring | `getDiagnostics` |
| **Build** | Chạy static check, xác nhận không có lỗi import hay syntax | `getDiagnostics` |
| **Run Check** | Viết và chạy script kiểm thử nhanh bằng `venv\Scripts\python.exe` để xác nhận code chạy đúng | `executePwsh` |

> ⚠️ **Lưu ý môi trường:** Luôn dùng `venv\Scripts\python.exe` (Windows) thay vì `python` trực tiếp để đảm bảo đúng interpreter của project có đủ dependencies.

```
┌──────────────────────────────────────────────────────────────────┐
│                    AI EXECUTION FLOW                             │
│                                                                  │
│   [Task nhận được]                                               │
│        │                                                         │
│        ▼                                                         │
│   Bước 1: Đọc file liên quan → Xác định side effects            │
│        │                                                         │
│        ▼                                                         │
│   Bước 2: Trình bày kế hoạch → Chờ xác nhận ──────────► STOP   │
│        │ (confirmed)                                             │
│        ▼                                                         │
│   Bước 3: Implement từng phần nhỏ                               │
│        │                                                         │
│        ▼                                                         │
│        ├─► Review: Đọc lại file đã sửa, getDiagnostics          │
│        │                                                         │
│        ├─► Build: Kiểm tra import/syntax không lỗi              │
│        │                                                         │
│        └─► Run Check: venv\Scripts\python.exe <test_script>     │
│                 │                                                │
│                 ├── PASS → Báo cáo hoàn thành                   │
│                 └── FAIL → Sửa lỗi → Lặp lại Review/Build/Run  │
└──────────────────────────────────────────────────────────────────┘
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
| Nhận task mới | Discovery → Proposal → Confirm → Implement → Review/Build/Run | Code ngay lập tức |
| Phát hiện code smell | Báo cáo, hỏi ý kiến | Tự ý refactor |
| Hoàn thành function | Cung cấp Example Usage / Unit Test | Không có verification |
| Thêm thư viện mới | Xin phép Tech Lead | Tự ý thêm vào requirements |
| Xuất code thay đổi | Diff-Only + Context Header | Viết lại toàn bộ file lớn |

---

## 10. AI Token Optimization Protocol (Giao thức Tối ưu hóa Token AI)

> **Mục tiêu:** Giảm thiểu lượng Token tiêu thụ trong mỗi phiên làm việc với AI mà không làm giảm chất lượng code. Mỗi Token tiêu thụ không cần thiết là một khoản chi phí phát triển lãng phí.

---

### 10.1. Quy tắc Đầu ra (Output Rules) — BẮT BUỘC TUYỆT ĐỐI

#### Quy tắc #1: Diff-Only Output (Chỉ xuất phần thay đổi)

> ❌ **NGHIÊM CẤM AI viết lại toàn bộ nội dung của một file** khi chỉ có một phần nhỏ thay đổi.

Khi cần sửa một hàm trong file dài, AI **chỉ được** xuất:
1. Tên file và phạm vi dòng bị ảnh hưởng.
2. Đoạn code cũ cần xóa (nếu có).
3. Đoạn code mới thay thế.

```
# ✅ ĐÚNG — Diff-Only Output
# File: src/apps/trading/bot_engine.py, lines 45-62

# [XÓA ĐOẠN CŨ]
- result = await exchange.fetch_ohlcv(symbol, timeframe)

# [THÊM ĐOẠN MỚI]
+ candles_1m = await self._adapter.fetch_latest_1m_candles(symbol, limit=500)
+ result = self._resampler.resample(candles_1m, timeframe)
```

```
# ❌ SAI — Viết lại toàn bộ file 300 dòng chỉ để sửa 2 dòng
```

#### Quy tắc #2: Context Header — Chống lỗi Ghép mã (Syntax Stitching Risk)

> ❌ **NGHIÊM CẤM** xuất đoạn code diff mà không có context header bọc ngoài.

Khi xuất code dạng hiệu chỉnh (diff), AI **bắt buộc** bao bọc đoạn thay đổi bằng **tên hàm/class chứa nó** (context header) hoặc **signature dòng** để người tích hợp biết chính xác vị trí dán vào. Mục đích: ngăn chặn lỗi thụt lề `IndentationError` và lỗi dán sai vị trí khi tích hợp thủ công.

```python
# ✅ ĐÚNG — Có context header rõ ràng
# File: src/core/data_pipeline/integrity_guard.py
# Class: DataIntegrityGuard
# Method: _check_gap() — THAY THẾ TOÀN BỘ METHOD NÀY

    def _check_gap(self, candles: list[Candle1m]) -> IntegrityCheckResult | None:
        # ... nội dung mới ...
```

```python
# ❌ SAI — Chỉ xuất snippet trơ, không biết dán vào đâu
    for i in range(1, len(candles)):
        delta = candles[i].open_time - candles[i-1].open_time
        if delta.total_seconds() > 90:
            return IntegrityCheckResult(...)
```

#### Quy tắc #3: Single Function Output (Xuất từng hàm)

Khi implement module mới có nhiều hàm, AI **bắt buộc**:
1. Liệt kê danh sách tất cả các hàm cần viết **trước**.
2. Viết từng hàm **một lần một**, chờ xác nhận trước khi viết hàm tiếp theo.
3. **Không được** dump cả class nếu tổng số dòng > 100.

```
# ✅ ĐÚNG — Quy trình Single Function Output
# AI: "Tôi sẽ viết DataIntegrityGuard theo thứ tự:
#   (1) __init__() + _check_gap()
#   (2) _check_warmup()
#   (3) _check_outlier()
#   (4) validate()  ← hàm orchestrator
# Bắt đầu với (1). Confirm để tôi tiếp tục (2)?"
```

---

### 10.2. Quy tắc Yêu cầu (Request Rules) — Dành cho Tech Lead

| Thay vì... | Hãy dùng... |
|---|---|
| "Viết module data pipeline" | "Viết hàm `_check_gap()` trong `DataIntegrityGuard`" |
| "Sửa bot engine" | "Sửa method `_run_cycle()` trong `bot_engine.py` tại dòng 45-62" |
| "Cập nhật tài liệu" | "Bổ sung mục 3.5 vào `DATA_ARCHITECTURE_GUIDELINES.md`" |

> **Nguyên tắc:** Yêu cầu càng cụ thể → AI đọc ít file hơn → Tiêu thụ ít Token hơn.

---

### 10.3. Tái khẳng định Kỷ luật Code Bắt buộc

#### Hàm ngắn ≤ 50 dòng

> ❌ **NGHIÊM CẤM** viết hàm dài hơn 50 dòng code thực thi (không tính docstring/comment).

```python
# ❌ SAI — Hàm "God" 150 dòng
async def run_full_cycle(self, symbol: str) -> None:
    # fetch + resample + validate + strategy + order — tất cả trong 1 hàm

# ✅ ĐÚNG — Orchestrator gọi các sub-function ≤ 50 dòng
async def run_full_cycle(self, symbol: str) -> None:
    df      = await self._fetch_and_resample(symbol)
    result  = await self._validate_data(df)
    if not result.is_valid:
        return
    signal  = await self._run_strategy(df)
    await self._execute_signal(signal)
```

#### 100% Type Hinting

```python
# ❌ SAI
def validate(self, candles, strategy_config):
    ...

# ✅ ĐÚNG
def validate(
    self,
    candles: list[ResampledCandle],
    strategy_config: StrategyConfig,
) -> IntegrityCheckResult:
    ...
```

#### Docstring Google Style

```python
def validate(
    self,
    candles: list[ResampledCandle],
    strategy_config: StrategyConfig,
) -> IntegrityCheckResult:
    """Kiểm tra tính toàn vẹn của dữ liệu trước khi đưa vào Strategy.

    Thực hiện 3 kiểm tra theo thứ tự: Gap → Warmup → Outlier.
    Dừng và trả về BLOCK ngay khi phát hiện vi phạm đầu tiên.

    Args:
        candles: Danh sách nến đã Resample, sắp xếp theo thời gian tăng dần.
        strategy_config: Cấu hình chiến lược, chứa `min_candles_required`.

    Returns:
        IntegrityCheckResult với `is_valid=True` nếu tất cả kiểm tra qua,
        hoặc `is_valid=False` kèm `reason` và `heal_event` nếu cần Self-Healing.

    Raises:
        ValueError: Nếu `candles` là danh sách rỗng.
    """
```

---

### 10.4. Ma trận Chi phí Token (Token Cost Matrix)

| Hành động | Token ước lượng | Đánh giá |
|---|---|---|
| Đọc file < 100 dòng | ~200 Token | ✅ Chấp nhận |
| Đọc file 300 dòng | ~600 Token | ⚠️ Chỉ đọc phần cần (StartLine/EndLine) |
| Đọc file > 500 dòng | ~1,000+ Token | ❌ Tránh — dùng grep/search trước |
| Viết lại toàn bộ file 300 dòng | ~700 Token | ❌ Cấm — dùng Diff-Only |
| Viết 1 hàm ≤ 50 dòng (Diff-Only + Header) | ~150 Token | ✅ Tối ưu |
| Lập kế hoạch / Phân tích kiến trúc | ~300 Token | ✅ Đầu tư có giá trị |

> **Quy tắc ngón tay cái:** Nếu một tác vụ tốn hơn 500 Token, hãy tìm cách chia nhỏ hơn.

---

### 10.5. Token Optimization Self-Check (Bổ sung vào AI Self-Check — Chương 6)

```
┌──────────────────────────────────────────────────────────────────────┐
│         TOKEN OPTIMIZATION SELF-CHECK (Chapter 10 Extension)        │
├─────┬────────────────────────────────────────────────────────────────┤
│  6  │ Tôi có đang viết lại toàn bộ file > 100 dòng không?           │
│     │ Nếu CÓ → Chuyển sang Diff-Only Output ngay.                   │
│  7  │ File tôi sắp đọc có > 300 dòng không? Tôi có cần đọc toàn    │
│     │ bộ, hay chỉ cần đọc phần liên quan (StartLine/EndLine)?       │
│  8  │ Module tôi sắp viết có > 100 dòng không?                      │
│     │ Nếu CÓ → Single Function Output, viết từng hàm, chờ confirm.  │
│  9  │ Đoạn Diff tôi vừa viết có Context Header chưa?                │
│     │ Nếu CHƯA → Bọc vào tên class/method/file + số dòng ngay.     │
└─────┴────────────────────────────────────────────────────────────────┘
```

