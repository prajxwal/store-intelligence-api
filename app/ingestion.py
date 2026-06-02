"""
POST /events/ingest — Event ingestion endpoint.
Accepts Purplle's sample event schema with flexible field names.
Validates, deduplicates, and stores events in batches.
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
    """Insert a single event with all enriched fields."""
    try:
        eid = event.get_effective_id()
        sid = event.get_effective_store()
        vid = event.get_effective_visitor()
        ts = event.get_effective_timestamp()

        await db.execute(
            """INSERT OR IGNORE INTO events
               (event_id, store_id, camera_id, visitor_id, track_id,
                event_type, timestamp,
                zone_id, zone_name, zone_type, is_revenue_zone,
                zone_hotspot_x, zone_hotspot_y,
                dwell_ms, is_staff, confidence,
                gender_pred, age_pred, age_bucket, is_face_hidden,
                group_id, group_size,
                queue_join_ts, queue_served_ts, queue_exit_ts,
                wait_seconds, queue_position_at_join, abandoned,
                queue_depth, sku_zone, session_seq)
               VALUES (?, ?, ?, ?, ?,
                       ?, ?,
                       ?, ?, ?, ?,
                       ?, ?,
                       ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?,
                       ?, ?, ?,
                       ?, ?, ?,
                       ?, ?, ?)""",
            (
                eid, sid, event.camera_id, vid, event.track_id,
                event.event_type.value, ts,
                event.zone_id, event.zone_name, event.zone_type, event.is_revenue_zone,
                event.zone_hotspot_x, event.zone_hotspot_y,
                event.dwell_ms, 1 if event.is_staff else 0, event.confidence,
                event.gender_pred, event.age_pred, event.age_bucket,
                1 if event.is_face_hidden else (0 if event.is_face_hidden is not None else None),
                event.group_id, event.group_size,
                event.queue_join_ts, event.queue_served_ts, event.queue_exit_ts,
                event.wait_seconds, event.queue_position_at_join,
                1 if event.abandoned else (0 if event.abandoned is not None else None),
                event.metadata.queue_depth if event.metadata else None,
                event.metadata.sku_zone if event.metadata else None,
                event.metadata.session_seq if event.metadata else None,
            ),
        )
        return db.total_changes > 0
    except Exception as e:
        logger.error(f"Failed to insert event {event.get_effective_id()}: {e}")
        raise


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(batch: EventBatch):
    """
    Ingest a batch of up to 500 events.
    Accepts Purplle's sample schema with flexible field names.
    Deduplicates by event_id (idempotent). Returns partial success.
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
                    event_id=event.get_effective_id(),
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
                    event_id=raw_event.get("event_id") or raw_event.get("queue_event_id"),
                    error=str(e),
                ))

        await db.commit()
    finally:
        await db.close()

    return IngestResponse(accepted=accepted, rejected=rejected, errors=errors)
