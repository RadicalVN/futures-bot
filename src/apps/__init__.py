# src/apps — Bounded Context Applications
# Mỗi sub-package là một App độc lập theo mô hình Modular Monolith.
# Quy tắc: KHÔNG import chéo giữa các apps. Giao tiếp qua DB hoặc Redis Event.
