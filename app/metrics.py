"""
GET /stores/{store_id}/metrics — Real-time store metrics.
Aligned with Purplle's lowercase event types and enriched POS data.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import MetricsResponse, ZoneDwell, GenderSplit, AgeBucketCount

logger = logging.getLogger("store_intelligence")
router = APIRouter()


@router.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
async def get_metrics(store_id: str, target_date: str | None = None):
    """Returns real-time metrics including demographics and brand analytics."""
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
                 AND event_type = 'entry'
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        unique_visitors = row["cnt"] if row else 0

        # Total events for the day
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE store_id = ? AND DATE(timestamp) = ?",
            (store_id, today),
        )
        row = await cursor.fetchone()
        total_events = row["cnt"] if row else 0

        # Unique purchases from POS (by distinct order_time)
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT order_time) as cnt
               FROM pos_transactions
               WHERE store_id = ?
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        total_purchases = row["cnt"] if row else 0

        # Conversion rate
        conversion_rate = 0.0
        if unique_visitors > 0 and total_purchases > 0:
            # Correlated: visitors in billing zone near a POS transaction
            cursor = await db.execute(
                """SELECT COUNT(DISTINCT e.visitor_id) as converted
                   FROM events e
                   JOIN pos_transactions p ON e.store_id = p.store_id
                   WHERE e.store_id = ?
                     AND e.is_staff = 0
                     AND e.zone_type = 'BILLING'
                     AND e.event_type IN ('zone_entered', 'queue_completed')
                     AND DATE(e.timestamp) = ?
                     AND ABS(JULIANDAY(e.timestamp) - JULIANDAY(p.timestamp)) * 24 * 60 <= 5""",
                (store_id, today),
            )
            row = await cursor.fetchone()
            converted = row["converted"] if row else 0

            if converted > 0:
                conversion_rate = round(converted / unique_visitors, 4)
            else:
                conversion_rate = round(min(total_purchases / unique_visitors, 1.0), 4)

        # Avg dwell per zone
        cursor = await db.execute(
            """SELECT zone_id, zone_name, zone_type,
                      AVG(dwell_ms) as avg_dwell,
                      COUNT(*) as visit_count
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type = 'zone_dwell'
                 AND zone_id IS NOT NULL
                 AND DATE(timestamp) = ?
               GROUP BY zone_id""",
            (store_id, today),
        )
        rows = await cursor.fetchall()
        avg_dwell_by_zone = [
            ZoneDwell(
                zone_id=r["zone_id"],
                zone_name=r["zone_name"],
                zone_type=r["zone_type"],
                avg_dwell_ms=round(r["avg_dwell"], 1),
                visit_count=r["visit_count"],
            )
            for r in rows
        ]

        # Current queue depth
        cursor = await db.execute(
            """SELECT queue_position_at_join
               FROM events
               WHERE store_id = ?
                 AND event_type IN ('queue_completed', 'queue_abandoned')
                 AND DATE(timestamp) = ?
               ORDER BY timestamp DESC
               LIMIT 1""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        current_queue_depth = row["queue_position_at_join"] if row and row["queue_position_at_join"] else 0

        # Avg wait seconds
        cursor = await db.execute(
            """SELECT AVG(wait_seconds) as avg_wait
               FROM events
               WHERE store_id = ?
                 AND event_type IN ('queue_completed', 'queue_abandoned')
                 AND wait_seconds IS NOT NULL
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        avg_wait_seconds = round(row["avg_wait"], 1) if row and row["avg_wait"] else 0.0

        # Abandonment rate
        cursor = await db.execute(
            """SELECT
                 SUM(CASE WHEN abandoned = 1 THEN 1 ELSE 0 END) as abandoned_cnt,
                 COUNT(*) as total_cnt
               FROM events
               WHERE store_id = ?
                 AND event_type IN ('queue_completed', 'queue_abandoned')
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        abandonment_rate = 0.0
        if row and row["total_cnt"] and row["total_cnt"] > 0:
            abandonment_rate = round((row["abandoned_cnt"] or 0) / row["total_cnt"], 4)

        # Gender split
        cursor = await db.execute(
            """SELECT gender_pred, COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND event_type = 'entry'
                 AND is_staff = 0
                 AND DATE(timestamp) = ?
               GROUP BY gender_pred""",
            (store_id, today),
        )
        rows = await cursor.fetchall()
        gender = GenderSplit()
        for r in rows:
            g = r["gender_pred"]
            if g == "M":
                gender.male = r["cnt"]
            elif g == "F":
                gender.female = r["cnt"]
            else:
                gender.unknown = r["cnt"]

        # Age distribution
        cursor = await db.execute(
            """SELECT age_bucket, COUNT(DISTINCT visitor_id) as cnt
               FROM events
               WHERE store_id = ?
                 AND event_type = 'entry'
                 AND is_staff = 0
                 AND age_bucket IS NOT NULL
                 AND DATE(timestamp) = ?
               GROUP BY age_bucket
               ORDER BY age_bucket""",
            (store_id, today),
        )
        rows = await cursor.fetchall()
        age_distribution = [AgeBucketCount(bucket=r["age_bucket"], count=r["cnt"]) for r in rows]

        # Top brands from POS
        cursor = await db.execute(
            """SELECT brand_name, COUNT(*) as item_count, SUM(total_amount) as revenue
               FROM pos_transactions
               WHERE store_id = ?
                 AND brand_name IS NOT NULL AND brand_name != ''
                 AND DATE(timestamp) = ?
               GROUP BY brand_name
               ORDER BY revenue DESC
               LIMIT 10""",
            (store_id, today),
        )
        rows = await cursor.fetchall()
        top_brands = [
            {"brand": r["brand_name"], "items_sold": r["item_count"], "revenue": round(r["revenue"], 2)}
            for r in rows
        ]

        return MetricsResponse(
            store_id=store_id,
            date=today,
            unique_visitors=unique_visitors,
            conversion_rate=conversion_rate,
            total_purchases=total_purchases,
            total_events=total_events,
            avg_dwell_by_zone=avg_dwell_by_zone,
            current_queue_depth=current_queue_depth,
            avg_wait_seconds=avg_wait_seconds,
            abandonment_rate=abandonment_rate,
            gender_split=gender,
            age_distribution=age_distribution,
            top_brands=top_brands,
        )

    finally:
        await db.close()
