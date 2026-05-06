Tôi là Tech Lead. Chúng ta sẽ thực hiện Task [Tên Task] cho dự án Trading Multi-Bot.

Yêu cầu nghiêm ngặt:

Tuân thủ cấu trúc thư mục tại /core và /apps. Không gọi chéo hàm giữa các App.

Sử dụng Type Hinting cho mọi function.

Nếu là Background Job, phải sử dụng bộ khung tại core.scheduler.

Trạng thái phải được lưu vào PostgreSQL/Redis, không dùng biến in-memory cho các dữ liệu quan trọng.

Log mọi lỗi vào hệ thống log tập trung.

Hãy phân tích kiến trúc trước khi viết code.