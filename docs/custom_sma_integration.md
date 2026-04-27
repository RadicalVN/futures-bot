# Tích Hợp Chỉ Báo Custom SMA (ittuantruong)

Tài liệu này mô tả chi tiết quá trình porting và tích hợp hệ thống chỉ báo Custom SMA từ Pine Script (TradingView) sang Hệ thống Bot Giao Dịch Python.

## 1. Kiến trúc Hệ Thống
Việc tích hợp Custom SMA được chia làm 2 phần chính để đảm bảo hiệu năng và tính tái sử dụng:
1. **Trading Strategy (`src/strategies/custom_sma.py`)**: Đóng vai trò là Não Bộ. Phân tích giá trị các nến để ra quyết định đóng/mở vị thế LONG/SHORT theo real-time. Tín hiệu trả về được gói trong đối tượng `StrategySignal` cùng với `metadata` chứa trạng thái của hệ thống.
2. **Chart Indicators (`src/data/indicators.py`)**: Đóng vai trò Cỗ Máy Tính Toán Khối Lượng Lớn. File này xử lý các phép tính trên mảng Numpy và Pandas cho hàng ngàn nến cùng lúc để phục vụ việc hiển thị lên UI Dashboard một cách nhanh nhất.

## 2. Chi tiết các thành phần hiển thị
Tất cả các thành phần trực quan từ TradingView đã được port thành công sang Web Dashboard (`chart.js`), bao gồm:
- **TVT-Trend (Bong bóng/Chấm tròn)**: Chạy bám theo hai dải băng giá (Upper/Lower Band). Tự động chuyển màu Xanh (Uptrend) và Đỏ/Vàng (Downtrend).
- **TVT-MA (Đường cong SMA Cơ sở)**: Hiển thị sự mượt mà của xu hướng. Sử dụng thuật toán đổi màu theo gia tốc của đoạn thẳng nối 2 nến (Xanh nếu dốc lên, Đỏ nếu dốc xuống).
- **TVT-MA-Cross (Dấu thập tự)**: Hiển thị cường độ gia tốc theo 6 màu sắc:
  - `Xanh dương` (Tăng gia tốc lên)
  - `Cam`, `Tím` (Giảm đà lên)
  - `Đỏ` (Tăng gia tốc xuống)
  - `Xanh lá`, `Vàng` (Giảm đà xuống / Sideway)

## 3. Tính năng Trải nghiệm & Tương tác Biểu Đồ (Advanced UI/UX)
Để mang lại trải nghiệm giống TradingView, hệ thống đã được nâng cấp với các tính năng sau:
- **Current Price Plugin**: Tự động vẽ một đường đứt nét cắt ngang biểu đồ cùng một nhãn (tag) hình mũi tên hiển thị giá mới nhất, màu sắc tự động đổi (xanh/đỏ) theo nến hiện tại.
- **Auto-Refresh & Time Tracking**: Tự động làm mới dữ liệu nến định kỳ mỗi 15 giây mà không làm mất trạng thái Zoom/Pan của biểu đồ. Đi kèm là bộ đếm trạng thái làm mới (VD: "Vừa cập nhật", "Cập nhật 15s trước").
- **Infinite Lazy-Loading (Kéo thả vô tận)**: Khi người dùng kéo (Pan) biểu đồ về phía lề trái, hệ thống sẽ ngầm gọi API với tham số `endTime` để nối liền (concat) dữ liệu lịch sử vào biểu đồ một cách mượt mà. Kéo sát lề phải sẽ ép buộc làm mới ngay lập tức.
- **Persist State**: Lưu trữ toàn bộ tuỳ chọn hiển thị (bật/tắt đường chỉ báo), symbol và khung thời gian (timeframe) vào `localStorage`. Việc F5 hay tải lại trang sẽ không làm mất cấu hình đã chỉnh sửa.

## 4. Các Vấn Đề Kỹ Thuật Đã Xử Lý
- **Lỗi NaN Serialize (500 Internal Server Error)**: Pandas mặc định dùng `NaN` (`np.float64(nan)`) khi một số nến ban đầu chưa đủ dữ liệu tính trung bình. FastAPI mặc định không hỗ trợ serialize `np.nan` sang JSON, gây lỗi crash 500. **Giải pháp**: Xử lý chặn vòng lặp, ép thủ công `NaN` thành `None` (Null trong JSON) bằng `pd.isna()`.
- **Lỗi đè trục Y giữa các Subchart**: Chart.js có bug hiển thị text đè lấn lên nhau khi gộp 2 trục Y trong cùng một canvas theo cơ chế xếp chồng (Stacking). **Giải pháp**: Chèn script chặn render Text tại đường chỉ ranh giới của trục.
- **Chuẩn màu Nến Nhật (Candlestick)**: Thư viện `chartjs-chart-financial` có xu hướng ép nến Tăng thành màu Xanh lá đặc ruột. **Giải pháp**: Can thiệp sâu vào `Chart.defaults.elements.candlestick` của thư viện JS, cấu hình nến tăng rỗng ruột (màu trong suốt) với viền đen.

## 5. Tham khảo thêm
- Mã gốc Pine Script: xem tại `docs/custom_sma_pinescript.md`
