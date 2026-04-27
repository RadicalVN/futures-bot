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

## 4. Tính Năng Dual-Chart Synchronization (Đồng bộ Đa Khung Thời Gian)
Hệ thống đã được nâng cấp lên kiến trúc Multi-Chart (2 biểu đồ song song) cho phép phân tích đa khung thời gian với tính năng đồng bộ chuyên sâu mô phỏng chuẩn TradingView Premium:
- **Đồng bộ Thao Tác Cơ Bản**: Thay đổi mã (Symbol), Làm mới (Refresh) hoặc Khôi phục Mặc định (Reset) trên bất kỳ biểu đồ nào sẽ lập tức đồng bộ lên biểu đồ còn lại. Khung thời gian bên phải luôn được ràng buộc phải lớn hơn khung bên trái ít nhất 1 bậc.
- **Đồng bộ Kích Thước Nến (Proportional Pan/Zoom Sync)**: Khi kéo thả (Pan) hoặc thu phóng (Zoom) trên một biểu đồ, biểu đồ kia sẽ tự động thu phóng theo với một tỷ lệ (ratio) chính xác dựa trên sự chênh lệch của khung thời gian (VD: 5m và 15m có tỷ lệ 1:3). Điều này đảm bảo **độ rộng (width) của các cây nến** trên 2 màn hình luôn tương đương nhau (số lượng nến bằng nhau) và mốc thời gian của cạnh phải luôn được neo chặt.
- **Đồng bộ Thông Số & Tooltip (Ghost Cursor)**: Áp dụng cơ chế giả lập sự kiện chuột ảo (Cross-Dispatching MouseEvents) để đồng bộ hoàn hảo Tooltip và đường gióng (Crosshair). Khi rê chuột ở biểu đồ 1, thông số của cây nến thuộc cùng một mốc thời gian ở biểu đồ 2 sẽ tự động bật lên.
- **Custom HTML Legend Dropdown**: Tối ưu không gian bằng cách giấu các nút Ẩn/Hiện đường tín hiệu vào một menu Dropdown nhỏ gọn ở góc trên bên trái biểu đồ. Mọi thao tác click ẩn/hiện ở biểu đồ này đều lập tức áp dụng cho cả biểu đồ kia.

## 5. Trọng Số Độ Dốc & Gia Tốc (Slope & Momentum Weights)
Để giải quyết vấn đề nhiễu tín hiệu khi dải băng (Trend) đổi màu nhưng lực không đủ mạnh, hệ thống đã được bổ sung thêm 2 trọng số nội suy:
- **Độ dốc (Slope Percentage - `% Dốc`)**: Tính toán tỷ lệ phần trăm chênh lệch giữa giá trị SMA nến hiện tại và nến liền trước (`(current - prev) / prev * 100`). Trọng số này biểu thị việc SMA đang cắm đầu xuống hay ngóc đầu lên mạnh cỡ nào.
- **Gia tốc (Momentum Percentage - `% Gia tốc`)**: Tính toán sự chênh lệch phần trăm giữa giá trị SMA thực tế và giá trị SMA kỳ vọng (dự phóng theo nội suy tuyến tính từ 2 nến trước đó). Trọng số này biểu thị lực đẩy nội tại.
**Ứng dụng**:
- **Trực quan UI**: Cả 2 thông số này được truyền trực tiếp qua API và hiển thị minh bạch lên Tooltip khi người dùng rê chuột vào đường `TVT-MA` hoặc node `TVT-MA-Cross`.
- **Logic Vào Lệnh (Bot Strategy)**: Người dùng có thể cấu hình 2 tham số `min_slope_pct` và `min_momentum_pct` để ép Bot **từ chối (bỏ qua) tín hiệu** nếu sóng quá yếu (mức dốc và gia tốc chưa đạt ngưỡng). Lịch sử tính toán và quyết định này sẽ được in ra mục Reason để dễ dàng tracking.

## 6. Các Vấn Đề Kỹ Thuật Đã Xử Lý
- **Lỗi NaN Serialize (500 Internal Server Error)**: Pandas mặc định dùng `NaN` (`np.float64(nan)`) khi một số nến ban đầu chưa đủ dữ liệu tính trung bình. FastAPI mặc định không hỗ trợ serialize `np.nan` sang JSON, gây lỗi crash 500. **Giải pháp**: Xử lý chặn vòng lặp, ép thủ công `NaN` thành `None` (Null trong JSON) bằng `pd.isna()`.
- **Lỗi đè trục Y giữa các Subchart**: Chart.js có bug hiển thị text đè lấn lên nhau khi gộp 2 trục Y trong cùng một canvas theo cơ chế xếp chồng (Stacking). **Giải pháp**: Chèn script chặn render Text tại đường chỉ ranh giới của trục.
- **Chuẩn màu Nến Nhật (Candlestick)**: Thư viện `chartjs-chart-financial` có xu hướng ép nến Tăng thành màu Xanh lá đặc ruột. **Giải pháp**: Can thiệp sâu vào `Chart.defaults.elements.candlestick` của thư viện JS, cấu hình nến tăng rỗng ruột (màu trong suốt) với viền đen.

## 7. Tham khảo thêm
- Mã gốc Pine Script: xem tại `docs/custom_sma_pinescript.md`
