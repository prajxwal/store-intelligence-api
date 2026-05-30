"""
GET /health — Health check endpoint.
Returns service status, last event per store, STALE_FEED warnings.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.database import get_db, check_db_health
from app.models import HealthResponse, StoreHealth

logger = logging.getLogger("store_intelligence")
router = APIRouter()

# Set at application startup
_start_time: float = time.time()


def set_start_time():
    global _start_time
    _start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """
    Returns service health:
    - Overall status
    - Uptime
    - Last event timestamp per store
    - STALE_FEED warning if any store's last event > 10 minutes ago
    - Database connectivity
    """
    db_healthy = await check_db_health()

    if not db_healthy:
        return HealthResponse(
            status="degraded",
            uptime_seconds=round(time.time() - _start_time, 1),
            stores=[],
            database="disconnected",
        )

    db = await get_db()
    try:
        # Get last event per store
        cursor = await db.execute(
            """SELECT store_id,
                      MAX(timestamp) as last_event_at,
                      COUNT(*) as event_count
               FROM events
               GROUP BY store_id"""
        )
        rows = await cursor.fetchall()

        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(minutes=10)
        stores = []

        for row in rows:
            last_event_str = row["last_event_at"]
            try:
                last_event = datetime.fromisoformat(last_event_str.replace("Z", "+00:00"))
                # Compare naive datetimes
                last_event_naive = last_event.replace(tzinfo=None)
                status = "STALE_FEED" if last_event_naive < stale_threshold else "OK"
            except Exception:
                status = "STALE_FEED"
                last_event = None

            stores.append(StoreHealth(
                store_id=row["store_id"],
                last_event_at=last_event_str,
                event_count=row["event_count"],
                status=status,
            ))

        overall_status = "healthy"
        if any(s.status == "STALE_FEED" for s in stores):
            overall_status = "warning"

        return HealthResponse(
            status=overall_status,
            uptime_seconds=round(time.time() - _start_time, 1),
            stores=stores,
            database="connected",
        )

    finally:
        await db.close()
