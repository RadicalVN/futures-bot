from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

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
