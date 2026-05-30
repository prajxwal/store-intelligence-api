"""
GET /stores/{store_id}/funnel — Conversion funnel endpoint.
Returns Entry → Zone Visit → Billing Queue → Purchase with counts and drop-off %.
Session-based (unique visitor_id), not raw event counts.
Re-entries do not double-count visitors.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import FunnelResponse, FunnelStage

logger = logging.getLogger("store_intelligence")
router = APIRouter()


@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_funnel(store_id: str, target_date: str | None = None):
    """
    Returns the conversion funnel:
    1. Entry — unique visitors who entered the store
    2. Zone Visit — visitors who visited at least one product zone
    3. Billing Queue — visitors who reached the billing/cash counter area
    4. Purchase — visitors correlated with a POS transaction (5-min window)
    
    Each stage shows count and drop-off % from the previous stage.
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

        # Stage 1: Entry — unique customer visitors
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type IN ('ENTRY', 'REENTRY')
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        entry_count = row["cnt"] if row else 0

        # Stage 2: Zone Visit — visitors who entered any product zone
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
                 AND zone_id IS NOT NULL
                 AND zone_id NOT IN ('BILLING', 'CASH_COUNTER', 'BILLING_AREA', 'ENTRY')
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        zone_visit_count = row["cnt"] if row else 0

        # Stage 3: Billing Queue — visitors who reached billing zone
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND (event_type IN ('BILLING_QUEUE_JOIN', 'ZONE_ENTER')
                      AND zone_id IN ('BILLING', 'CASH_COUNTER', 'BILLING_AREA'))
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        billing_count = row["cnt"] if row else 0

        # Stage 4: Purchase — visitors correlated with POS transactions
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT e.visitor_id) as cnt
               FROM events e
               JOIN pos_transactions p ON e.store_id = p.store_id
               WHERE e.store_id = ?
                 AND e.is_staff = 0
                 AND e.zone_id IN ('BILLING', 'CASH_COUNTER', 'BILLING_AREA')
                 AND DATE(e.timestamp) = ?
                 AND ABS(JULIANDAY(e.timestamp) - JULIANDAY(p.timestamp)) * 24 * 60 <= 5""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        purchase_count = row["cnt"] if row else 0

        # If no direct correlation, fall back to POS transaction count as a proxy
        if purchase_count == 0 and billing_count > 0:
            cursor = await db.execute(
                """SELECT COUNT(DISTINCT transaction_id) as cnt
                   FROM pos_transactions
                   WHERE store_id = ?
                     AND DATE(timestamp) = ?""",
                (store_id, today),
            )
            row = await cursor.fetchone()
            pos_count = row["cnt"] if row else 0
            purchase_count = min(pos_count, billing_count)

        # Build funnel stages with drop-off
        stages = []

        stages.append(FunnelStage(
            stage="Entry",
            count=entry_count,
            drop_off_pct=0.0,
        ))

        drop_off = round((1 - zone_visit_count / entry_count) * 100, 1) if entry_count > 0 else 0.0
        stages.append(FunnelStage(
            stage="Zone Visit",
            count=zone_visit_count,
            drop_off_pct=drop_off,
        ))

        drop_off = round((1 - billing_count / zone_visit_count) * 100, 1) if zone_visit_count > 0 else 0.0
        stages.append(FunnelStage(
            stage="Billing Queue",
            count=billing_count,
            drop_off_pct=drop_off,
        ))

        drop_off = round((1 - purchase_count / billing_count) * 100, 1) if billing_count > 0 else 0.0
        stages.append(FunnelStage(
            stage="Purchase",
            count=purchase_count,
            drop_off_pct=drop_off,
        ))

        return FunnelResponse(store_id=store_id, stages=stages)

    finally:
        await db.close()
