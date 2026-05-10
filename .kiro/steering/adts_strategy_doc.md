---
inclusion: fileMatch
fileMatchPattern: "src/strategies/adts_strategy.py"
---

# Steering: ADTS Strategy Document Sync

Khi bạn chỉnh sửa file `src/strategies/adts_strategy.py`, bạn **bắt buộc** phải cập nhật `docs/adts_strategy.md` trong cùng một lần thay đổi.

## Các trường hợp cần cập nhật

| Thay đổi trong code | Phần cần cập nhật trong docs/adts_strategy.md |
|---|---|
| Thêm/sửa tham số trong `PARAMETERS_SCHEMA` | Mục 3 — Parameters |
| Thêm/sửa indicator | Mục 2 — Indicators Sử Dụng |
| Thay đổi điều kiện entry (LONG/SHORT) | Mục 4.3 — Entry Signal |
| Thay đổi exit logic (SL, TP1, TP2, Emergency) | Mục 4.4 — Exit Logic |
| Thay đổi calibration logic | Mục 4.1 — Daily Calibration |
| Thay đổi Shield conditions | Mục 4.2 — The Shield |
| Thay đổi `_OrderState` / `_CalibrationResult` | Mục 5 — Cấu Trúc Dữ Liệu |
| Thay đổi `prepare_metadata()` output | Mục 5.3 — Metadata |
| Thay đổi `get_required_lookback()` | Mục 4.1 — lookback |
| Fix một backlog item | Mục 7 — Backlog (đánh dấu RESOLVED) |

## Quy trình bắt buộc

1. Hoàn thành thay đổi code trong `adts_strategy.py`.
2. Mở `docs/adts_strategy.md`.
3. Cập nhật đúng mục tương ứng theo bảng trên.
4. Cập nhật **Version History** ở đầu file với version mới, ngày, và mô tả thay đổi.
5. Nếu thay đổi liên quan đến kiến trúc (contract, indicator migration), cập nhật thêm `src/ARCHITECTURE_GUIDELINES.md`.

## Format Version History

```markdown
| v1.x | YYYY-MM-DD | Mô tả ngắn gọn thay đổi |
```
