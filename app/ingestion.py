"""
POST /events/ingest — Event ingestion endpoint.
Validates, deduplicates, and stores events in batches.
Idempotent by event_id. Supports partial success.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import EventBatch, EventIngest, EventError, IngestResponse

logger = logging.getLogger("store_intelligence")
router = APIRouter()


async def _insert_event(db, event: EventIngest) -> bool:
    """Insert a single event. Returns True if inserted, False if duplicate."""
    try:
        await db.execute(
            """INSERT OR IGNORE INTO events 
               (event_id, store_id, camera_id, visitor_id, event_type, 
                timestamp, zone_id, dwell_ms, is_staff, confidence,
                queue_depth, sku_zone, session_seq)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.store_id,
                event.camera_id,
                event.visitor_id,
                event.event_type.value,
                event.timestamp.isoformat(),
                event.zone_id,
                event.dwell_ms,
                1 if event.is_staff else 0,
                event.confidence,
                event.metadata.queue_depth,
                event.metadata.sku_zone,
                event.metadata.session_seq,
            ),
        )
        return db.total_changes > 0
    except Exception as e:
        logger.error(f"Failed to insert event {event.event_id}: {e}")
        raise


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(batch: EventBatch):
    """
    Ingest a batch of up to 500 events.
    
    - Validates each event against the schema
    - Deduplicates by event_id (idempotent)
    - Returns partial success on malformed events
    """
    if len(batch.events) == 0:
        return IngestResponse(accepted=0, rejected=0, errors=[])

    try:
        db = await get_db()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": "Database connection failed"}
        )

    accepted = 0
    rejected = 0
    errors: list[EventError] = []

    try:
        for idx, event in enumerate(batch.events):
            try:
                await _insert_event(db, event)
                accepted += 1
            except Exception as e:
                rejected += 1
                errors.append(EventError(
                    index=idx,
                    event_id=event.event_id,
                    error=str(e),
                ))

        await db.commit()
    finally:
        await db.close()

    logger.info(f"Ingested batch: accepted={accepted}, rejected={rejected}")
    return IngestResponse(accepted=accepted, rejected=rejected, errors=errors)


@router.post("/events/ingest/raw")
async def ingest_raw_events(events: list[dict[str, Any]]):
    """
    Alternative ingest endpoint accepting raw JSON list.
    Validates each event individually for maximum flexibility.
    """
    if len(events) > 500:
        raise HTTPException(
            status_code=400,
            detail={"error": "batch_too_large", "message": "Maximum 500 events per batch"}
        )

    try:
        db = await get_db()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": "Database connection failed"}
        )

    accepted = 0
    rejected = 0
    errors: list[EventError] = []

    try:
        for idx, raw_event in enumerate(events):
            try:
                event = EventIngest(**raw_event)
                await _insert_event(db, event)
                accepted += 1
            except Exception as e:
                rejected += 1
                errors.append(EventError(
                    index=idx,
                    event_id=raw_event.get("event_id"),
                    error=str(e),
                ))

        await db.commit()
    finally:
        await db.close()

    return IngestResponse(accepted=accepted, rejected=rejected, errors=errors)
