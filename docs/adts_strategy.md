# ADTS Strategy — Tài Liệu Kỹ Thuật

> **Adaptive Dynamic Trend & Shield**
>
> File: `src/strategies/adts_strategy.py`
> `STRATEGY_NAME = "adts"`
>
> **Self-Update Rule:** AI bắt buộc cập nhật file này mỗi khi có thay đổi logic, tham số,
> hoặc cấu trúc của chiến lược ADTS. Cập nhật phải nằm trong cùng commit với thay đổi code.

---

## Version History

| Version | Ngày | Thay đổi |
|---|---|---|
| v1.0 | 2026-05-10 | Khởi tạo document — tổng hợp từ source code sau Phase 4 refactor |
| | | - Migrate từ `src/strategies/adts/` package sang single-file `adts_strategy.py` |
| | | - Tất cả indicator logic chuyển sang `src/data/indicators.py` |
| | | - Implement đầy đủ Zero-Core-Edit contract (BaseStrategy) |
| v1.1 | 2026-05-10 | Fix [ADTS-001] State Loss khi Restart |
| | | - Thêm `_OrderState.to_dict()` / `_OrderState.from_dict()` — serialize/deserialize state |
| | | - Thêm `_persist_order_state()` — async, ghi vào `Trade.signal_metadata["adts_order_state"]` |
| | | - Thêm `restore_order_states_from_db()` — public, reconstruct state khi bot restart |
| | | - `register_order_state()` nhận thêm `bot_id` và tự động persist sau khi đăng ký |
| | | - `_check_tp1()` persist state sau khi TP1 hit và SL dời về entry |
| | | - `_check_tp2_trail()` persist trailing stop sau mỗi lần cập nhật |
| v1.2 | 2026-05-10 | Fix [ADTS-002] Calibration Fallback — bot không còn bị tê liệt khi thiếu dữ liệu D1 |
| | | - `_CalibrationResult`: thêm property `is_hardcoded_default`, `age_hours` |
| | | - `_ensure_calibration()`: đổi return type `Optional` → `_CalibrationResult` (không bao giờ None) |
| | | - Implement 3 tầng fallback: Fresh → Stale → Hardcoded Default |
| | | - Thêm classmethod `_make_hardcoded_calibration()` với giá trị conservative |
| | | - `analyze()`: xóa None check, thêm per-cycle WARNING khi dùng hardcoded |
| | | - `_build_metadata()`: thêm `calibration_is_stale`, `calibration_is_default` |
| v1.3 | 2026-05-10 | Fix [ADTS-003] Emergency Exit 2 Giai Đoạn |
| | | - `_OrderState`: thêm field `emergency_triggered: bool = False` |
| | | - `to_dict()` / `from_dict()`: persist `emergency_triggered`, backward-compat với dict cũ |
| | | - `_check_emergency_exit()`: refactor thành 3 nhánh (Giai đoạn 1, Giai đoạn 2, Recovery) |
| | | - Tách `_detect_emergency_condition()` — Single Responsibility, ≤50 dòng |
| | | - Giai đoạn 1: cập nhật `amount_remaining` ngay để PnL Giai đoạn 2 chính xác |
| | | - Persist state ngay sau Giai đoạn 1 và Recovery qua `asyncio.create_task()` |
| v1.4 | 2026-05-11 | [INF-001] Per-symbol Async Safety Lock cho `_order_states` |
| | | - `__init__()`: thêm `_order_states_locks: dict[str, asyncio.Lock] = {}` |
| | | - `_get_order_state_lock(symbol)`: helper tạo/lấy lock per-symbol |
| | | - `analyze()`: bọc lock quanh Read-Modify-Write (get + _check_exits + pop) |
| | | - `register_order_state()`: đổi thành `async def`, bọc lock quanh dict write |
| | | - `clear_order_state()`: đổi thành `async def`, bọc lock + cleanup lock sau xóa |
| | | - `restore_order_states_from_db()`: lock per-symbol quanh từng write, I/O DB ngoài lock |

---

## 1. Tổng Quan

ADTS là chiến lược giao dịch xu hướng có bộ lọc sideway thích nghi. Điểm khác biệt so với các chiến lược MA/MACD thông thường:

- **Calibration hàng ngày (D1):** Tự động tính ngưỡng sideway từ dữ liệu D1 thay vì hardcode.
- **The Shield — 3 lớp lọc:** ADX + BBWidth + EMA Slope phải đồng thời vượt ngưỡng.
- **SL/TP động theo ATR:** Không dùng % cố định, thích nghi với volatility thực tế.
- **Thoát lệnh 2 tầng:** TP1 chốt 50% + TP2 trailing stop cho phần còn lại.
- **Emergency Exit:** Thoát sớm khi thị trường mất xu hướng đột ngột.

### Luồng xử lý

```
[Calibration D1 — mỗi 26h]
        │
        ▼
[The Shield Filter]
  ADX > threshold?
  BBWidth > sideway_threshold?
  |EMA20_slope| > min_slope?
        │ PASS
        ▼
[Exit Checks — ưu tiên trước entry]
  Emergency Exit → Stop Loss → TP1 → TP2 Trail
        │ Không có exit
        ▼
[Entry Signal]
  LONG:  close > EMA20 + slope > 0 + close > EMA200
  SHORT: close < EMA20 + slope < 0 + close < EMA200
```

---

## 2. Indicators Sử Dụng

Tất cả indicator được tính qua `src/data/indicators.py` — không implement lại trong strategy file.

| Indicator | Hàm | Tham số mặc định | Mục đích |
|---|---|---|---|
| ATR | `add_atr_to_df()` | period=14, Wilder's RMA | Tính SL/TP động, Min_Slope |
| ADX | `add_adx_to_df()` | period=14, Wilder's method | The Shield — điều kiện 1 |
| Bollinger Bands Width | `add_bbwidth_to_df()` | period=20, std=2.0 | The Shield — điều kiện 2 |
| EMA + Slope | `add_ema_slope_to_df()` | period=20 | Entry signal + The Shield — điều kiện 3 |
| EMA200 | inline `ewm()` | period=200 | Trend Filter (Long/Short direction) |
| ATR (D1) | `add_atr_to_df()` | period=14 trên D1 | Calibration — Base_ATR |
| BBWidth (D1) | `add_bbwidth_to_df()` | period=20, std=2.0 trên D1 | Calibration — Sideway_Threshold |

Snapshot tổng hợp tất cả giá trị tại nến cuối: `build_adts_snapshot()` → `ADTSSnapshot`.

---

## 3. Tham Số (Parameters)

### 3.1 Indicator Periods

| Tham số | Kiểu | Mặc định | Min | Max | Mô tả |
|---|---|---|---|---|---|
| `timeframe` | string | `"5m"` | — | — | Khung thời gian nến intraday |
| `atr_period` | int | `14` | 2 | 50 | Chu kỳ ATR cho D1 calibration và SL/TP |
| `adx_period` | int | `14` | 2 | 50 | Chu kỳ ADX cho The Shield |
| `ema_period` | int | `20` | 2 | 200 | Chu kỳ EMA entry signal |
| `ema200_period` | int | `200` | 50 | 500 | Chu kỳ EMA trend filter |
| `bb_period` | int | `20` | 5 | 100 | Chu kỳ Bollinger Bands |
| `bb_std` | float | `2.0` | 0.5 | 5.0 | Hệ số std Bollinger Bands |
| `bbwidth_sma_period` | int | `200` | 10 | 500 | Chu kỳ SMA của BBWidth trên D1 |

### 3.2 Shield Thresholds

| Tham số | Kiểu | Mặc định | Min | Max | Mô tả |
|---|---|---|---|---|---|
| `adx_threshold` | float | `20.0` | 5.0 | 60.0 | ADX phải vượt ngưỡng này |
| `bbwidth_threshold_factor` | float | `1.0` | 0.5 | 2.0 | Hệ số nhân SMA(BBWidth) để tính Sideway_Threshold |
| `min_slope_atr_factor` | float | `0.05` | 0.01 | 0.5 | Hệ số ATR để tính Min_Slope = Base_ATR × factor / 5 |

### 3.3 Risk Management

| Tham số | Kiểu | Mặc định | Min | Max | Mô tả |
|---|---|---|---|---|---|
| `leverage` | int | `5` | 1 | 125 | Đòn bẩy giao dịch |
| `position_size_pct` | float | `0.1` | 0.01 | 1.0 | Tỷ lệ vốn mỗi lệnh (0.0–1.0) |
| `sl_atr_mult` | float | `1.5` | 0.5 | 5.0 | Hệ số ATR cho Stop Loss |
| `hard_sl_pct` | float | `0.03` | 0.005 | 0.2 | Hard SL tối đa theo % giá entry |
| `tp1_rr` | float | `1.2` | 0.5 | 5.0 | Tỷ lệ R:R cho TP1 |
| `tp1_close_pct` | float | `0.5` | 0.1 | 1.0 | Tỷ lệ % vị thế chốt tại TP1 |
| `tp2_trail_atr_mult` | float | `2.0` | 0.5 | 10.0 | Hệ số ATR cho Trailing Stop TP2 |

### 3.4 Emergency Exit

| Tham số | Kiểu | Mặc định | Min | Max | Mô tả |
|---|---|---|---|---|---|
| `emergency_adx_threshold` | float | `20.0` | 5.0 | 50.0 | ADX dưới ngưỡng này → Emergency Exit |
| `emergency_close_pct` | float | `0.5` | 0.1 | 1.0 | Tỷ lệ % vị thế đóng khi Emergency |

---

## 4. Logic Chi Tiết

### 4.1 Daily Calibration

**Tần suất:** Chạy lại khi `_CalibrationResult.is_stale == True` (age > 26 giờ).

**Quy trình:**
1. Resample dữ liệu intraday (5m) → D1 bằng pandas `resample("1D").agg(OHLCV)`.
2. Tính `ATR(14)` trên D1 → `Base_ATR`.
3. Tính `BBWidth(20, 2.0)` trên D1, lấy `SMA(BBWidth, bbwidth_sma_period)` → `bbwidth_sma_val`.
4. `Sideway_Threshold = bbwidth_sma_val × bbwidth_threshold_factor`.
5. `Min_Slope = Base_ATR × min_slope_atr_factor / 5`.

**Yêu cầu dữ liệu tối thiểu:** `bbwidth_sma_period + atr_period + 10` nến D1 (mặc định ≥ 224).

**Lookback intraday:** `bbwidth_sma_period × 10 + 100` nến 5m (mặc định **2100 nến ≈ 7.3 ngày**).

**Lưu ý:** Calibration dùng `asyncio.Lock` để tránh race condition khi nhiều symbol chạy song song.

**Cơ chế 3 tầng Fallback (v1.2):** `_ensure_calibration()` luôn trả về `_CalibrationResult`, không bao giờ `None`:

| Tầng | Điều kiện | Hành động | Log Level |
|---|---|---|---|
| **1 — Fresh** | Đủ dữ liệu D1, tính toán thành công | Cập nhật `self._calibration` | INFO ✅ |
| **2 — Stale** | Tầng 1 thất bại + có calibration cũ | Dùng tạm calibration cũ (dù > 26h) | WARNING ⚠️ |
| **3 — Hardcoded** | Cả 2 tầng trên thất bại | Dùng giá trị conservative (`sideway_threshold=0`, `min_slope=1e-9`) | CRITICAL 🚨 |

Khi Tầng 3 active: Shield chỉ còn ADX filter hoạt động thực sự. Bot vẫn giao dịch nhưng thiếu bộ lọc sideway từ D1.

### 4.2 The Shield — Sideway Filter

```
adx_ok     = ADX(14) > adx_threshold
bbwidth_ok = BBWidth(20, 2.0) > sideway_threshold   ← từ D1 calibration
slope_ok   = |EMA20[i] - EMA20[i-1]| > min_slope   ← từ D1 calibration

shield.passed = adx_ok AND bbwidth_ok AND slope_ok
```

Nếu `shield.passed == False` → trả về `signal="none"`, không kiểm tra entry.

### 4.3 Entry Signal

Chỉ kiểm tra khi `shield.passed == True` và không có vị thế đang mở (`pos_side is None`).

**LONG:**
```
close > EMA20
AND EMA20_slope > 0
AND close > EMA200
```

**SHORT:**
```
close < EMA20
AND EMA20_slope < 0
AND close < EMA200
```

**Tính SL/TP khi entry:**
```
sl_distance  = min(sl_atr_mult × ATR, entry_price × hard_sl_pct)
tp1_distance = sl_distance × tp1_rr

LONG:
  SL  = entry_price - sl_distance
  TP1 = entry_price + tp1_distance
  TP2_trail_init = entry_price - tp2_trail_atr_mult × ATR

SHORT:
  SL  = entry_price + sl_distance
  TP1 = entry_price - tp1_distance
  TP2_trail_init = entry_price + tp2_trail_atr_mult × ATR
```

**Confidence score:** `0.5 + min((ADX - adx_threshold) / 25, 1.0) × 0.5` → range [0.5, 1.0].

### 4.4 Exit Logic — Thứ tự ưu tiên

Exit được kiểm tra **trước** entry trong mỗi cycle.

#### 4.4.1 Emergency Exit (ưu tiên cao nhất) — 2 Giai Đoạn

Kích hoạt khi **một trong hai** điều kiện:
- `ADX < emergency_adx_threshold` (xu hướng suy yếu)
- `BBWidth < sideway_threshold` (thị trường nén lại)

**Giai đoạn 1** (`emergency_triggered = False`):
- Đóng `emergency_close_pct` (50%) vị thế.
- Set `emergency_triggered = True`, cập nhật `amount_remaining`.
- Persist state ngay lập tức.
- `full_close = False` — vị thế còn lại tiếp tục theo dõi.

**Giai đoạn 2** (`emergency_triggered = True`, điều kiện vẫn vi phạm):
- Đóng 100% `amount_remaining`.
- `full_close = True` — xóa `_OrderState`.

**Recovery** (`emergency_triggered = True`, Shield phục hồi):
- Reset `emergency_triggered = False`.
- Tiếp tục giữ 50% vị thế còn lại, theo dõi SL/TP2 trail bình thường.

#### 4.4.2 Stop Loss

```
LONG:  low <= stop_loss  → đóng 100%, giá = min(SL, close)
SHORT: high >= stop_loss → đóng 100%, giá = max(SL, close)
```

#### 4.4.3 TP1 — Chốt 50%

```
LONG:  high >= take_profit_1
SHORT: low  <= take_profit_1
```

Sau khi TP1 hit:
- Đóng `tp1_close_pct` (50%) vị thế.
- `stop_loss` dời về `entry_price` (breakeven protection).
- `take_profit_2_trail` reset về `tp1` (bắt đầu trailing từ đây).
- `amount_remaining = amount_total × (1 - tp1_close_pct)`.

#### 4.4.4 TP2 — Trailing Stop (chỉ sau TP1)

Trailing stop cập nhật mỗi nến theo cơ chế ratchet (chỉ di chuyển theo hướng có lợi):
```
LONG:  new_trail = close - tp2_trail_atr_mult × ATR
       take_profit_2_trail = max(take_profit_2_trail, new_trail)

SHORT: new_trail = close + tp2_trail_atr_mult × ATR
       take_profit_2_trail = min(take_profit_2_trail, new_trail)
```

Kích hoạt đóng 100% khi:
```
LONG:  low  <= take_profit_2_trail
SHORT: high >= take_profit_2_trail
```

---

## 5. Cấu Trúc Dữ Liệu

### 5.1 Dataclasses nội bộ

| Class | Mô tả | Vòng đời |
|---|---|---|
| `_CalibrationResult` | Base_ATR, Sideway_Threshold, Min_Slope từ D1. Properties: `is_stale`, `is_hardcoded_default`, `age_hours` | In-memory, stale sau 26h |
| `_ShieldState` | Trạng thái 3 điều kiện Shield tại nến hiện tại | Tính lại mỗi cycle |
| `_OrderState` | Trạng thái đầy đủ lệnh đang mở. Fields: `tp1_hit`, `sl_moved_to_entry`, `emergency_triggered`, `amount_remaining` | In-memory + DB (v1.1) |
| `ADTSSnapshot` | Snapshot tất cả indicator tại nến cuối | Tính lại mỗi cycle |

### 5.2 State persistence

| Dữ liệu | Nơi lưu | Bền vững |
|---|---|---|
| `_OrderState` per symbol | `ADTSStrategy._order_states` (dict) + `Trade.signal_metadata["adts_order_state"]` | ✅ DB (v1.1) |
| Trade record | Bảng `trades` (SQLite) | ✅ DB |
| Entry opportunity | Bảng `entry_opportunities` (SQLite) | ✅ DB |
| `_CalibrationResult` | `ADTSStrategy._calibration` | ❌ In-memory |

**Cơ chế persist (v1.1):**
- Sau mỗi lần state thay đổi (entry, TP1 hit, trailing update), `_persist_order_state()` được gọi qua `asyncio.create_task()` — non-blocking.
- State được ghi vào `Trade.signal_metadata["adts_order_state"]` dưới dạng dict JSON.
- Khi bot restart, `restore_order_states_from_db()` query tất cả Trade OPEN của strategy "adts" và reconstruct `_order_states` từ key này.
- Lỗi persist được log WARNING và bỏ qua — không làm crash cycle chính.

### 5.3 Metadata trả về trong StrategySignal

```python
{
    # Indicator values
    "close": float, "high": float, "low": float,
    "atr": float, "adx": float, "bb_width": float,
    "ema20": float, "ema20_slope": float, "ema200": float,
    "above_ema200": bool,

    # Calibration
    "base_atr_d1": float,
    "sideway_threshold": float,
    "min_slope": float,
    "calibrated_at": str,  # ISO format
    "calibration_is_stale": bool,    # True nếu calibration đã > 26h (Tầng 2)
    "calibration_is_default": bool,  # True nếu đang dùng hardcoded default (Tầng 3)

    # Shield status
    "shield_passed": bool,
    "adx_ok": bool, "bbwidth_ok": bool, "slope_ok": bool,

    # Entry-specific (chỉ có khi signal là entry)
    "entry_price": float, "stop_loss": float,
    "take_profit_1": float, "tp2_initial_trail": float,
    "sl_distance": float, "sl_source": str,  # "ATR" | "Hard"
    "atr_at_entry": float,

    # Exit-specific (chỉ có khi signal là exit)
    "partial_close": bool, "partial_pct": float, "full_close": bool,
}
```

---

## 6. Tích Hợp với Platform

### 6.1 BotEngine

- `StrategyFactory.create("adts", parameters)` → tự động tìm `ADTSStrategy` qua `pkgutil`.
- `get_required_lookback(parameters)` → trả về `bbwidth_sma_period × 10 + 100` (mặc định 2100).
- `requires_one_shot_check = False` → không giới hạn 1 lệnh/phase.
- Sau `initialize()`, nên gọi `await strategy.restore_order_states_from_db(bot_id)` để restore state khi restart.

### 6.2 ExitMonitorService

- Gọi `strategy.prepare_metadata(df)` mỗi 30 giây cho mỗi Trade OPEN.
- `prepare_metadata()` trả về: `adx`, `bb_width`, `ema20_slope`, `close`, `high`, `low`, `atr`, `sideway_threshold`, `emergency_adx_threshold`.
- `_check_exit_condition()` dùng metadata này để quyết định đóng lệnh.

### 6.3 Khung thời gian hỗ trợ

`PARAMETERS_SCHEMA` khai báo: `1m, 3m, 5m, 15m, 30m, 1h, 4h`.
Tối ưu và đang chạy production: **5m**.

### 6.4 Cặp tiền đang chạy

| Bot ID | Symbol | Ghi chú |
|---|---|---|
| Bot #7 | BTCUSDT | Production |
| Bot #9 | BTCUSDT | Production |
| Bot #10 | BTCUSDT | Production |
| Bot #11 | BTCUSDT | Production |

---

## 7. Backlog — Vấn Đề Cần Xử Lý

### 🔴 Critical

#### [ADTS-001] ✅ RESOLVED — v1.1 (2026-05-10)

**Vấn đề:** `_order_states` dict in-memory không được persist vào DB. Khi bot restart (deploy, crash), toàn bộ trạng thái TP1/trailing/SL-dời-về-entry bị mất.

**Giải pháp đã implement:**
- `_OrderState.to_dict()` / `from_dict()` — serialize/deserialize state.
- `_persist_order_state()` — ghi vào `Trade.signal_metadata["adts_order_state"]` sau mỗi thay đổi.
- `restore_order_states_from_db()` — reconstruct state khi bot restart.
- Gọi persist tại: `register_order_state()`, `_check_tp1()`, `_check_tp2_trail()`.

---

### 🟡 Medium

#### [ADTS-002] ✅ RESOLVED — v1.2 (2026-05-10)

**Vấn đề:** Nếu không đủ nến D1 (< 224 nến), `_run_calibration()` trả về `None` và bot không vào lệnh. Không có cơ chế fallback dùng calibration cũ hoặc giá trị mặc định.

**Giải pháp đã implement:**
- `_CalibrationResult`: thêm property `is_hardcoded_default` (d1_candles_used == 0) và `age_hours`.
- `_ensure_calibration()`: đổi return type `Optional[_CalibrationResult]` → `_CalibrationResult` (không bao giờ None).
- 3 tầng fallback: Tầng 1 (Fresh) → Tầng 2 (Stale, log WARNING) → Tầng 3 (Hardcoded, log CRITICAL).
- `_make_hardcoded_calibration()`: classmethod tạo giá trị conservative (`sideway_threshold=0.0`, `min_slope=1e-9`).
- `analyze()`: xóa None check, thêm per-cycle WARNING khi `calibration.is_hardcoded_default`.
- `_build_metadata()`: thêm `calibration_is_stale` và `calibration_is_default` để dashboard cảnh báo.

---

#### [ADTS-003] ✅ RESOLVED — v1.3 (2026-05-10)

**Vấn đề:** Emergency Exit chỉ đóng 50% một lần, không có cơ chế đóng 100% còn lại nếu điều kiện emergency tiếp diễn.

**Giải pháp đã implement:**
- `_OrderState`: thêm `emergency_triggered: bool = False`. `to_dict()`/`from_dict()` cập nhật, backward-compat với dict cũ.
- `_check_emergency_exit()`: refactor thành 3 nhánh — Giai đoạn 1 (đóng 50%, set flag, persist), Giai đoạn 2 (đóng 100% còn lại), Recovery (reset flag).
- `_detect_emergency_condition()`: tách riêng để tuân thủ Single Responsibility và giới hạn ≤50 dòng.
- Giai đoạn 1 cập nhật `amount_remaining` ngay để PnL Giai đoạn 2 chính xác tuyệt đối.
- Persist state ngay sau Giai đoạn 1 và Recovery qua `asyncio.create_task()`.

---

#### [ADTS-004] Backtesting Engine chưa tích hợp

**Vấn đề:** Không có backtesting engine tích hợp trong platform (Phase 4 chưa triển khai). Hiện tại dùng script `gen_backtest.py` chạy thủ công.

**Hệ quả:** Không thể đánh giá nhanh impact của việc thay đổi tham số (ADX threshold, sl_atr_mult, tp1_rr...).

---

### 🟢 Low

#### [ADTS-005] `_order_states` không thread-safe với multi-symbol

**Vấn đề:** `_order_states` là dict dùng chung cho tất cả symbol. Khi bot quét nhiều symbol song song qua `asyncio.gather`, có thể có race condition khi đọc/ghi dict.

**Ghi chú:** Trong CPython, dict assignment là atomic nên rủi ro thực tế thấp, nhưng cần xem xét khi scale lên nhiều symbol.

---

#### [ADTS-006] Confidence Score chưa được dùng để filter lệnh

**Vấn đề:** `_calc_confidence()` tính score dựa trên ADX strength (0.5–1.0) và gắn vào `StrategySignal.confidence`, nhưng `BotEngine` chưa có logic filter lệnh theo ngưỡng confidence tối thiểu.

**Giải pháp đề xuất:** Thêm tham số `min_confidence` vào `PARAMETERS_SCHEMA`. BotEngine đọc và so sánh với `signal.confidence` trước khi đặt lệnh.

---

## 8. Kết Quả Backtesting

> Backtesting engine chưa tích hợp vào platform (xem [ADTS-004]). Các file kết quả nằm tại `data/backtest/backtest_adts_*.xlsx`.

| File | Khoảng thời gian | Ghi chú |
|---|---|---|
| `backtest_adts_BTCUSDT_5m_20260101_20260502.xlsx` | 2026-01-01 → 2026-05-02 | 4 tháng Q1+Q2 |
| `backtest_adts_BTCUSDT_5m_20260101_20260503.xlsx` | 2026-01-01 → 2026-05-03 | Mở rộng +1 ngày |
| `backtest_adts_BTCUSDT_5m_20260403_20260503.xlsx` | 2026-04-03 → 2026-05-03 | Tháng 4/2026 |

*Cập nhật bảng này mỗi khi chạy backtest mới với kết quả Win-rate, Max Drawdown, Profit Factor.*

---

## 9. Hướng Dẫn Maintain

### Khi thay đổi tham số mặc định

1. Cập nhật bảng mục 3 (Parameters).
2. Cập nhật `PARAMETERS_SCHEMA` trong `adts_strategy.py`.
3. Chạy backtest để xác nhận impact.
4. Cập nhật Version History ở đầu file.

### Khi thêm indicator mới

1. Thêm hàm `add_xxx_to_df()` vào `src/data/indicators.py` (tuân thủ Indicator Migration Rule).
2. Cập nhật `build_adts_snapshot()` nếu indicator thuộc ADTS core.
3. Cập nhật bảng mục 2 (Indicators).
4. Cập nhật `ADTSSnapshot` dataclass nếu cần thêm field.

### Khi thay đổi exit logic

1. Cập nhật mục 4.4 (Exit Logic).
2. Kiểm tra `prepare_metadata()` — ExitMonitorService có cần thêm key mới không.
3. Cập nhật mục 5.3 (Metadata).

### Khi fix backlog item

1. Đánh dấu item là `✅ RESOLVED` trong mục 7.
2. Ghi ngày fix và version.
3. Cập nhật Version History.

### Checklist tự kiểm tra trước khi merge

```
[ ] Tham số mới đã được thêm vào PARAMETERS_SCHEMA
[ ] Indicator mới đã nằm trong src/data/indicators.py (không implement trong strategy)
[ ] prepare_metadata() trả về đủ key cho ExitMonitorService
[ ] get_required_lookback() đã tính đúng lookback mới nếu thêm indicator dài hạn
[ ] Version History đã được cập nhật
[ ] Backlog đã được cập nhật (thêm issue mới hoặc đóng issue cũ)
```
