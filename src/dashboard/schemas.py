from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
import re

# ── Comment sanitizer ─────────────────────────────────────────────────────────

_MAX_COMMENT_LENGTH: int = 500
"""Giới hạn độ dài comment (ký tự). Phải khớp với max_length trong Field."""

# Regex xóa HTML/script tags và ký tự control nguy hiểm
_SCRIPT_STYLE_RE  = re.compile(r'<(script|style)[^>]*>.*?</(script|style)>', re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE      = re.compile(r'<[^>]+>')
_CONTROL_CHAR_RE  = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_MULTI_SPACE_RE   = re.compile(r'[ \t]{3,}')   # 3+ spaces/tabs → 1 space
_MULTI_NEWLINE_RE = re.compile(r'\n{3,}')       # 3+ newlines → 2 newlines


def _sanitize_comment(value: str) -> Optional[str]:
    """Làm sạch comment người dùng: strip, xóa HTML, xóa control chars.

    Args:
        value: Chuỗi comment thô từ người dùng.

    Returns:
        Chuỗi đã làm sạch, hoặc None nếu rỗng sau khi clean.
    """
    # 1. Strip khoảng trắng hai đầu
    value = value.strip()
    if not value:
        return None

    # 2. Xóa nội dung bên trong <script> và <style> (kể cả nội dung)
    value = _SCRIPT_STYLE_RE.sub('', value)

    # 3. Xóa các HTML tag còn lại (chỉ tag, giữ text content)
    value = _HTML_TAG_RE.sub('', value)

    # 4. Xóa ký tự control nguy hiểm (null bytes, ESC, ...)
    value = _CONTROL_CHAR_RE.sub('', value)

    # 5. Normalize whitespace nội bộ (không xóa, chỉ gọn lại)
    value = _MULTI_SPACE_RE.sub(' ', value)
    value = _MULTI_NEWLINE_RE.sub('\n\n', value)

    # 6. Strip lại sau khi clean
    value = value.strip()
    return value if value else None

# --- Account Schemas ---
class AccountCreate(BaseModel):
    name: str = Field(..., description="Tên gợi nhớ tài khoản")
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    mode: str = Field("testnet", description="Môi trường chạy: testnet hoặc mainnet")

# --- Bot Schemas ---
class BotCreate(BaseModel):
    name: str = Field(..., description="Tên hiển thị của bot")
    account_id: int = Field(..., description="ID của tài khoản giao dịch")
    symbols: List[str] = Field(default=["BTCUSDT"], description="Danh sách các cặp tiền giao dịch")
    strategy_name: str = Field(default="ma_macd", description="Tên chiến lược bot sử dụng")
    parameters: Dict[str, Any] = Field(default={}, description="Các tham số cấu hình riêng cho chiến lược")

class BotStatusUpdate(BaseModel):
    status: str = Field(..., description="Trạng thái mong muốn: running, stopped")

class BotSettingsUpdate(BaseModel):
    """Cập nhật job behavior settings của bot"""
    allow_new_entry:  Optional[bool] = Field(None, description="Cho phép vào lệnh mới")
    notify_entry:     Optional[bool] = Field(None, description="Gửi noti khi tìm thấy entry")
    allow_exit_scan:  Optional[bool] = Field(None, description="Quét đóng lệnh / invalidate entry")
    notify_exit:      Optional[bool] = Field(None, description="Gửi noti khi đóng lệnh / entry")


# --- AI Feedback Schemas ---

class AIFeedbackCreate(BaseModel):
    """Schema để tạo phản hồi AI từ người dùng.

    Validation:
        - comment được sanitize: strip, xóa HTML tags, xóa control chars.
        - comment rỗng sau khi sanitize → None (không lưu).
        - comment vượt 500 ký tự → 422 Unprocessable Entity.
    """
    trade_id: Optional[int] = Field(None, description="ID của Trade (nullable nếu gắn với opp)")
    opp_id:   Optional[int] = Field(None, description="ID của EntryOpportunity (nullable)")
    rating:   str           = Field(...,  description="Đánh giá: 'like' hoặc 'dislike'")
    comment:  Optional[str] = Field(
        None,
        description="Ghi chú tùy chọn (tối đa 500 ký tự sau khi sanitize)",
        max_length=_MAX_COMMENT_LENGTH,
    )

    @field_validator("comment", mode="before")
    @classmethod
    def sanitize_comment(cls, value: Optional[str]) -> Optional[str]:
        """Sanitize comment: strip, xóa HTML/script, xóa control chars.

        Chạy TRƯỚC khi Pydantic kiểm tra max_length — đảm bảo length check
        áp dụng trên chuỗi đã clean, không phải chuỗi thô.

        Args:
            value: Giá trị comment thô từ request body.

        Returns:
            Chuỗi đã làm sạch, hoặc None nếu rỗng.

        Raises:
            ValueError: Nếu comment sau khi clean vượt _MAX_COMMENT_LENGTH.
        """
        if value is None:
            return None

        cleaned = _sanitize_comment(str(value))
        if cleaned is None:
            return None

        # Kiểm tra length sau khi clean (Pydantic max_length check cũng sẽ chạy,
        # nhưng validator này cho phép trả về error message rõ ràng hơn)
        if len(cleaned) > _MAX_COMMENT_LENGTH:
            raise ValueError(
                f"Comment vuot gioi han {_MAX_COMMENT_LENGTH} ky tu "
                f"(hien tai: {len(cleaned)} ky tu sau khi sanitize). "
                f"Vui long rut gon noi dung."
            )

        return cleaned
