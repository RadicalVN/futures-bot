"""
Migrate data từ SQLite sang PostgreSQL.
Chỉ migrate các bảng có data quan trọng: exchange_accounts, bots, trades, signals, bot_events.
Bỏ qua: ohlcv_candles (sẽ fetch lại), ohlcv_fetch_jobs/chunks (reset), system_settings.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

SQLITE_PATH = "data/trading.db"
TABLES = ["exchange_accounts", "bots", "bot_events", "trades", "signals", "entry_opportunities"]

# Các cột boolean theo từng bảng (SQLite lưu 0/1, PG cần True/False)
BOOL_COLS = {
    "exchange_accounts": {"is_active"},
    "bots": {"is_deleted", "allow_new_entry", "notify_entry", "allow_exit_scan", "notify_exit"},
    "trades": set(),
    "signals": {"executed"},
    "entry_opportunities": {"executed", "is_deleted"},
    "bot_events": set(),
}

# Các cột datetime (SQLite lưu string, PG cần datetime object)
import re
from datetime import datetime

def _parse_dt(val):
    """Chuyển string datetime sang datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    # Thử các format phổ biến
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(val), fmt)
        except ValueError:
            continue
    return None  # fallback

DATETIME_COLS = {
    "exchange_accounts": {"created_at"},
    "bots": {"created_at", "updated_at"},
    "trades": {"created_at", "updated_at", "closed_at"},
    "signals": {"timestamp"},
    "entry_opportunities": {"created_at", "invalidated_at"},
    "bot_events": {"timestamp"},
}

async def main():
    if not os.path.exists(SQLITE_PATH):
        print(f"⚠️  SQLite file không tồn tại: {SQLITE_PATH} — bỏ qua migrate")
        return

    import sqlite3
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    from dotenv import load_dotenv
    load_dotenv()

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    import os as _os
    pg_url = _os.getenv("DATABASE_URL")
    pg_engine = create_async_engine(pg_url)

    total_migrated = 0
    for table in TABLES:
        try:
            cursor = sqlite_conn.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
        except Exception as e:
            print(f"  ⚠️  Bỏ qua {table}: {e}")
            continue

        if not rows:
            print(f"  — {table}: trống, bỏ qua")
            continue

        cols = [d[0] for d in cursor.description]
        bool_cols = BOOL_COLS.get(table, set())
        dt_cols   = DATETIME_COLS.get(table, set())
        col_list  = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(f":{c}" for c in cols)

        inserted = 0
        async with pg_engine.begin() as conn:
            for row in rows:
                row_dict = dict(zip(cols, row))
                # Convert types
                for k, v in row_dict.items():
                    if v == "None":
                        row_dict[k] = None
                    elif k in bool_cols:
                        row_dict[k] = bool(v) if v is not None else None
                    elif k in dt_cols:
                        row_dict[k] = _parse_dt(v)
                    # JSON columns: SQLite lưu string, PG cần dict/list
                    # asyncpg tự handle nếu column type là JSONB/JSON
                try:
                    await conn.execute(
                        text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'),
                        row_dict,
                    )
                    inserted += 1
                except Exception as e:
                    print(f"    ⚠️  Row lỗi trong {table} id={row_dict.get('id')}: {str(e)[:120]}")

        print(f"  ✓ {table}: {inserted}/{len(rows)} rows migrated")
        total_migrated += inserted

    await pg_engine.dispose()
    sqlite_conn.close()
    print(f"\n✅ Migrate hoàn tất: {total_migrated} rows tổng cộng")

    # ── Reset PostgreSQL sequences ────────────────────────────────────────────
    # Sau khi migrate từ SQLite, sequences vẫn bắt đầu từ 1 → conflict khi insert mới.
    # Cần reset về max(id) + 1 cho tất cả bảng có serial PK.
    print("\n🔧 Đang reset PostgreSQL sequences...")
    SERIAL_TABLES = [
        "exchange_accounts", "bots", "bot_events", "trades",
        "signals", "entry_opportunities", "ohlcv_fetch_jobs", "ohlcv_fetch_chunks",
    ]
    pg_engine2 = create_async_engine(pg_url)
    async with pg_engine2.begin() as conn:
        for table in SERIAL_TABLES:
            result = await conn.execute(text(f'SELECT MAX(id) FROM "{table}"'))
            max_id = result.scalar() or 0
            await conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id + 1}, false)"
            ))
            print(f"  ✓ {table}: sequence → {max_id + 1}")
    await pg_engine2.dispose()
    print("✅ Sequences đã được reset!")

asyncio.run(main())
