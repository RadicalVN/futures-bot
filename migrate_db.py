"""
migrate_db.py — Thêm các cột và bảng mới vào DB hiện có
Chạy: python migrate_db.py
"""
import sqlite3

conn = sqlite3.connect('data/trading.db')
cur = conn.cursor()

migrations = [
    # Thêm stop_loss, take_profit vào trades
    "ALTER TABLE trades ADD COLUMN stop_loss REAL",
    "ALTER TABLE trades ADD COLUMN take_profit REAL",

    # Tạo bảng entry_opportunities
    """
    CREATE TABLE IF NOT EXISTS entry_opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
        symbol VARCHAR(20) NOT NULL,
        signal_type VARCHAR(10) NOT NULL,
        strategy VARCHAR(50),
        entry_price REAL,
        stop_loss REAL,
        take_profit REAL,
        leverage INTEGER DEFAULT 1,
        executed BOOLEAN DEFAULT 0,
        is_deleted BOOLEAN DEFAULT 0,
        delete_reason VARCHAR(200),
        metadata JSON DEFAULT '{}',
        reason VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        invalidated_at DATETIME
    )
    """,

    # Index để query nhanh
    "CREATE INDEX IF NOT EXISTS ix_entry_opp_bot_id ON entry_opportunities(bot_id)",
    "CREATE INDEX IF NOT EXISTS ix_entry_opp_symbol ON entry_opportunities(symbol)",
    "CREATE INDEX IF NOT EXISTS ix_entry_opp_is_deleted ON entry_opportunities(is_deleted)",
]

for sql in migrations:
    try:
        cur.execute(sql.strip())
        print(f"✅ OK: {sql.strip()[:60]}...")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            print(f"⏭️  Skip (already exists): {sql.strip()[:60]}...")
        else:
            print(f"❌ Error: {e} | SQL: {sql.strip()[:60]}...")

conn.commit()
conn.close()
print("\nMigration hoàn tất.")
