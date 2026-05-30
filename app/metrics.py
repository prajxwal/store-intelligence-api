"""
GET /stores/{store_id}/metrics — Real-time store metrics.
Computes unique visitors, conversion rate, avg dwell, queue depth, and abandonment rate.
Excludes staff from customer metrics. Handles zero-purchase stores.
"""

from __future__ import annotations

import logging
from datetime import datetime, date

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import MetricsResponse, ZoneDwell

logger = logging.getLogger("store_intelligence")
router = APIRouter()


@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
async def get_metrics(store_id: str, target_date: str | None = None):
    """
    Returns real-time metrics for a store:
    - Unique visitors (excluding staff)
    - Conversion rate (visitors in billing zone within 5-min of POS transaction / total visitors)
    - Avg dwell time per zone
    - Current queue depth
    - Abandonment rate
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

        # Unique customer visitors (exclude staff)
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt
               FROM events 
               WHERE store_id = ? 
                 AND is_staff = 0
                 AND event_type = 'ENTRY'
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        unique_visitors = row["cnt"] if row else 0

        # Total purchases from POS transactions for the day
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT transaction_id) as cnt
               FROM pos_transactions
               WHERE store_id = ?
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        total_purchases = row["cnt"] if row else 0

        # Conversion rate: visitors who were in billing zone within 5-min window before a POS txn
        # Fallback: if we have POS data, use purchase count / visitor count
        conversion_rate = 0.0
        if unique_visitors > 0 and total_purchases > 0:
            # Find visitors who were in the billing zone and had a correlated POS transaction
            cursor = await db.execute(
                """SELECT COUNT(DISTINCT e.visitor_id) as converted
                   FROM events e
                   JOIN pos_transactions p ON e.store_id = p.store_id
                   WHERE e.store_id = ?
                     AND e.is_staff = 0
                     AND e.zone_id IN ('BILLING', 'CASH_COUNTER', 'BILLING_AREA')
                     AND e.event_type IN ('ZONE_ENTER', 'BILLING_QUEUE_JOIN', 'ZONE_DWELL')
                     AND DATE(e.timestamp) = ?
                     AND ABS(JULIANDAY(e.timestamp) - JULIANDAY(p.timestamp)) * 24 * 60 <= 5""",
                (store_id, today),
            )
            row = await cursor.fetchone()
            converted = row["converted"] if row else 0

            if converted > 0:
                conversion_rate = round(converted / unique_visitors, 4)
            else:
                # Fallback: simple purchase/visitor ratio
                conversion_rate = round(min(total_purchases / unique_visitors, 1.0), 4)

        # Avg dwell per zone
        cursor = await db.execute(
            """SELECT zone_id, 
                      AVG(dwell_ms) as avg_dwell,
                      COUNT(*) as visit_count
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type = 'ZONE_DWELL'
                 AND zone_id IS NOT NULL
                 AND DATE(timestamp) = ?
               GROUP BY zone_id""",
            (store_id, today),
        )
        rows = await cursor.fetchall()
        avg_dwell_by_zone = [
            ZoneDwell(
                zone_id=r["zone_id"],
                avg_dwell_ms=round(r["avg_dwell"], 1),
                visit_count=r["visit_count"],
            )
            for r in rows
        ]

        # Current queue depth (latest BILLING_QUEUE_JOIN event)
        cursor = await db.execute(
            """SELECT queue_depth
               FROM events
               WHERE store_id = ?
                 AND event_type = 'BILLING_QUEUE_JOIN'
                 AND DATE(timestamp) = ?
               ORDER BY timestamp DESC
               LIMIT 1""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        current_queue_depth = row["queue_depth"] if row and row["queue_depth"] else 0

        # Abandonment rate: visitors who entered billing zone but no correlated purchase
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as billing_visitors
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND zone_id IN ('BILLING', 'CASH_COUNTER', 'BILLING_AREA')
                 AND event_type IN ('ZONE_ENTER', 'BILLING_QUEUE_JOIN')
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        billing_visitors = row["billing_visitors"] if row else 0

        abandonment_count = 0
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND event_type = 'BILLING_QUEUE_ABANDON'
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        abandonment_count = row["cnt"] if row else 0

        abandonment_rate = 0.0
        if billing_visitors > 0:
            abandonment_rate = round(abandonment_count / billing_visitors, 4)

        return MetricsResponse(
            store_id=store_id,
            date=today,
            unique_visitors=unique_visitors,
            conversion_rate=conversion_rate,
            total_purchases=total_purchases,
            avg_dwell_by_zone=avg_dwell_by_zone,
            current_queue_depth=current_queue_depth,
            abandonment_rate=abandonment_rate,
        )

    finally:
        await db.close()
