"""
patch7.py — Thêm 4 cột job behavior settings vào bảng bots:
  - allow_new_entry  BOOLEAN DEFAULT 1
  - notify_entry     BOOLEAN DEFAULT 1
  - allow_exit_scan  BOOLEAN DEFAULT 1
  - notify_exit      BOOLEAN DEFAULT 1
"""
import asyncio
from src.database.db import engine
from sqlalchemy import text


async def run():
    async with engine.begin() as conn:
        # Kiểm tra và thêm từng cột (SQLite không hỗ trợ ADD COLUMN IF NOT EXISTS)
        result = await conn.execute(text("PRAGMA table_info(bots)"))
        existing_cols = {row[1] for row in result.fetchall()}

        cols_to_add = {
            "allow_new_entry": "BOOLEAN DEFAULT 1 NOT NULL",
            "notify_entry":    "BOOLEAN DEFAULT 1 NOT NULL",
            "allow_exit_scan": "BOOLEAN DEFAULT 1 NOT NULL",
            "notify_exit":     "BOOLEAN DEFAULT 1 NOT NULL",
        }

        for col, definition in cols_to_add.items():
            if col not in existing_cols:
                await conn.execute(text(f"ALTER TABLE bots ADD COLUMN {col} {definition}"))
                print(f"✅ Đã thêm cột: {col}")
            else:
                print(f"⏭️  Cột đã tồn tại: {col}")

    print("✅ Migration patch7 hoàn tất.")


if __name__ == "__main__":
    asyncio.run(run())
