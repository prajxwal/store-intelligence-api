"""
GET /stores/{store_id}/heatmap — Zone heatmap endpoint.
Returns zone visit frequency + avg dwell, normalised 0–100.
Includes data_confidence flag when < 20 sessions.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import HeatmapResponse, ZoneHeat

logger = logging.getLogger("store_intelligence")
router = APIRouter()


@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(store_id: str, target_date: str | None = None):
    """
    Returns zone visit frequency and average dwell time,
    normalised to a 0–100 scale for heatmap rendering.
    """
    try:
        db = await get_db()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": "Database connection failed"}
        )

    try:
        today = target_date or date.today().isoformat()

        # Get zone-level aggregations
        cursor = await db.execute(
            """SELECT zone_id,
                      COUNT(DISTINCT visitor_id) as visit_count,
                      AVG(dwell_ms) as avg_dwell_ms
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND zone_id IS NOT NULL
                 AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL', 'ZONE_EXIT')
                 AND DATE(timestamp) = ?
               GROUP BY zone_id
               ORDER BY visit_count DESC""",
            (store_id, today),
        )
        rows = await cursor.fetchall()

        if not rows:
            return HeatmapResponse(
                store_id=store_id,
                data_confidence="low",
                zones=[],
            )

        # Find max visit count for normalisation
        max_visits = max(r["visit_count"] for r in rows) if rows else 1

        # Total unique sessions for confidence check
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as total_sessions
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type = 'ENTRY'
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        session_row = await cursor.fetchone()
        total_sessions = session_row["total_sessions"] if session_row else 0

        data_confidence = "normal" if total_sessions >= 20 else "low"

        zones = [
            ZoneHeat(
                zone_id=r["zone_id"],
                visit_count=r["visit_count"],
                avg_dwell_ms=round(r["avg_dwell_ms"] or 0, 1),
                normalised_score=round((r["visit_count"] / max_visits) * 100, 1) if max_visits > 0 else 0,
            )
            for r in rows
        ]

        return HeatmapResponse(
            store_id=store_id,
            data_confidence=data_confidence,
            zones=zones,
        )

    finally:
        await db.close()
