"""
Shared test fixtures for the Store Intelligence API test suite.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


def make_event(
    event_type: str = "ENTRY",
    store_id: str = "ST1008",
    visitor_id: str = None,
    zone_id: str = None,
    is_staff: bool = False,
    confidence: float = 0.85,
    dwell_ms: int = 0,
    timestamp: str = None,
    queue_depth: int = None,
) -> dict:
    """Factory function to create valid test events."""
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": "CAM_03",
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": event_type,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": zone_id,
            "session_seq": 1,
        },
    }


def make_visitor_journey(
    visitor_id: str = None,
    store_id: str = "ST1008",
    is_staff: bool = False,
    include_billing: bool = True,
    timestamp_base: str = "2026-04-10T18:00:00Z",
) -> list[dict]:
    """Create a complete visitor journey: ENTRY → zones → BILLING → EXIT."""
    vid = visitor_id or f"VIS_{uuid.uuid4().hex[:6]}"
    events = []
    
    # Entry
    events.append(make_event("ENTRY", store_id, vid, is_staff=is_staff,
                             timestamp=timestamp_base))
    
    # Zone visit
    events.append(make_event("ZONE_ENTER", store_id, vid, zone_id="SKINCARE",
                             is_staff=is_staff, timestamp="2026-04-10T18:01:00Z"))
    events.append(make_event("ZONE_DWELL", store_id, vid, zone_id="SKINCARE",
                             dwell_ms=45000, is_staff=is_staff, 
                             timestamp="2026-04-10T18:01:45Z"))
    events.append(make_event("ZONE_EXIT", store_id, vid, zone_id="SKINCARE",
                             is_staff=is_staff, timestamp="2026-04-10T18:02:00Z"))
    
    # Billing
    if include_billing:
        events.append(make_event("ZONE_ENTER", store_id, vid, zone_id="BILLING",
                                 is_staff=is_staff, timestamp="2026-04-10T18:03:00Z"))
        events.append(make_event("BILLING_QUEUE_JOIN", store_id, vid, zone_id="BILLING",
                                 is_staff=is_staff, timestamp="2026-04-10T18:03:10Z",
                                 queue_depth=2))
    
    # Exit
    events.append(make_event("EXIT", store_id, vid, is_staff=is_staff,
                             timestamp="2026-04-10T18:05:00Z"))
    
    return events


@pytest_asyncio.fixture
async def client():
    """Create a test client with fresh database for each test."""
    db_path = f"test_{uuid.uuid4().hex[:8]}.db"
    os.environ["DATABASE_PATH"] = db_path
    
    # Import after setting env var
    from app.database import init_db
    from app.main import app
    
    await init_db()
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    wal_path = db_path + "-wal"
    shm_path = db_path + "-shm"
    if os.path.exists(wal_path):
        os.remove(wal_path)
    if os.path.exists(shm_path):
        os.remove(shm_path)
