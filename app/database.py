"""
Database layer — SQLite with WAL mode via aiosqlite.
Schema aligned with Purplle's expected event format.
"""

from __future__ import annotations

import aiosqlite
import os
import logging

logger = logging.getLogger("store_intelligence")

def _get_db_path() -> str:
    return os.getenv("DATABASE_PATH", "store_intelligence.db")


async def get_db() -> aiosqlite.Connection:
    """Get a database connection with WAL mode enabled."""
    db = await aiosqlite.connect(_get_db_path())
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    return db


async def init_db():
    """Initialize database schema — aligned with Purplle sample schemas."""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                track_id INTEGER,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,

                -- Zone fields
                zone_id TEXT,
                zone_name TEXT,
                zone_type TEXT,
                is_revenue_zone TEXT,
                zone_hotspot_x REAL,
                zone_hotspot_y REAL,

                -- Duration
                dwell_ms INTEGER DEFAULT 0,

                -- Staff flag
                is_staff INTEGER DEFAULT 0,

                -- Detection
                confidence REAL DEFAULT 0.5,

                -- Demographics
                gender_pred TEXT,
                age_pred INTEGER,
                age_bucket TEXT,
                is_face_hidden INTEGER,
                group_id TEXT,
                group_size INTEGER,

                -- Queue timing
                queue_join_ts TEXT,
                queue_served_ts TEXT,
                queue_exit_ts TEXT,
                wait_seconds INTEGER,
                queue_position_at_join INTEGER,
                abandoned INTEGER,

                -- Legacy metadata
                queue_depth INTEGER,
                sku_zone TEXT,
                session_seq INTEGER,

                -- System
                ingested_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_events_store_id ON events(store_id);
            CREATE INDEX IF NOT EXISTS idx_events_visitor_id ON events(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_store_type ON events(store_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_events_store_visitor ON events(store_id, visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_zone ON events(store_id, zone_id);
            CREATE INDEX IF NOT EXISTS idx_events_gender ON events(store_id, gender_pred);

            CREATE TABLE IF NOT EXISTS pos_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                store_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                order_date TEXT,
                order_time TEXT,
                product_id TEXT,
                brand_name TEXT,
                total_amount REAL DEFAULT 0.0,
                customer_name TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pos_store ON pos_transactions(store_id);
            CREATE INDEX IF NOT EXISTS idx_pos_timestamp ON pos_transactions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_pos_brand ON pos_transactions(brand_name);
            CREATE INDEX IF NOT EXISTS idx_pos_order ON pos_transactions(order_id, order_time);
        """)
        await db.commit()
        logger.info("Database schema initialized successfully")
    finally:
        await db.close()


async def check_db_health() -> bool:
    """Check if database is accessible."""
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        await db.close()
        return True
    except Exception:
        return False
