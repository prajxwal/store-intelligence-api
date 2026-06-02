"""
GET /stores/{store_id}/anomalies — Anomaly detection endpoint.
Detects: BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE.
Each anomaly includes severity and suggested_action.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.models import AnomalyResponse, Anomaly, AnomalyType, Severity

logger = logging.getLogger("store_intelligence")
router = APIRouter()


@router.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
async def get_anomalies(store_id: str, target_date: str | None = None):
    """
    Returns active anomalies for a store:
    - BILLING_QUEUE_SPIKE: queue_depth exceeds 2× rolling average
    - CONVERSION_DROP: today's conversion < 7-day rolling avg by >20%
    - DEAD_ZONE: any zone with 0 visits in last 30 minutes
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
        now = datetime.now(timezone.utc)
        anomalies: list[Anomaly] = []

        # ── 1. BILLING_QUEUE_SPIKE ──────────────────────────────────────
        # Get current queue position
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
        current_queue = row["queue_position_at_join"] if row and row["queue_position_at_join"] else 0

        # Get average queue position for the day
        cursor = await db.execute(
            """SELECT AVG(queue_position_at_join) as avg_depth
               FROM events
               WHERE store_id = ?
                 AND event_type IN ('queue_completed', 'queue_abandoned')
                 AND queue_position_at_join IS NOT NULL
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        avg_queue = row["avg_depth"] if row and row["avg_depth"] else 0

        if current_queue > 0 and avg_queue > 0 and current_queue >= 2 * avg_queue:
            severity = Severity.CRITICAL if current_queue >= 3 * avg_queue else Severity.WARN
            anomalies.append(Anomaly(
                anomaly_type=AnomalyType.BILLING_QUEUE_SPIKE,
                severity=severity,
                description=f"Billing queue depth ({current_queue}) is {current_queue / avg_queue:.1f}× the average ({avg_queue:.1f})",
                suggested_action="Open additional billing counter or deploy staff to expedite checkout",
                detected_at=now,
            ))

        # ── 2. CONVERSION_DROP ──────────────────────────────────────────
        # Today's conversion rate
        cursor = await db.execute(
            """SELECT COUNT(DISTINCT visitor_id) as visitors
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type = 'entry'
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        today_visitors = row["visitors"] if row else 0

        cursor = await db.execute(
            """SELECT COUNT(DISTINCT order_time) as purchases
               FROM pos_transactions
               WHERE store_id = ?
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        row = await cursor.fetchone()
        today_purchases = row["purchases"] if row else 0

        today_conversion = today_purchases / today_visitors if today_visitors > 0 else 0.0

        # 7-day rolling average conversion
        seven_days_ago = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor = await db.execute(
            """SELECT DATE(timestamp) as day,
                      COUNT(DISTINCT visitor_id) as visitors
               FROM events
               WHERE store_id = ?
                 AND is_staff = 0
                 AND event_type = 'entry'
                 AND DATE(timestamp) BETWEEN ? AND ?
               GROUP BY DATE(timestamp)""",
            (store_id, seven_days_ago, today),
        )
        daily_visitors = {r["day"]: r["visitors"] for r in await cursor.fetchall()}

        cursor = await db.execute(
            """SELECT DATE(timestamp) as day,
                      COUNT(DISTINCT order_time) as purchases
               FROM pos_transactions
               WHERE store_id = ?
                 AND DATE(timestamp) BETWEEN ? AND ?
               GROUP BY DATE(timestamp)""",
            (store_id, seven_days_ago, today),
        )
        daily_purchases = {r["day"]: r["purchases"] for r in await cursor.fetchall()}

        daily_conversions = []
        for day in daily_visitors:
            if day != today and daily_visitors[day] > 0:
                rate = daily_purchases.get(day, 0) / daily_visitors[day]
                daily_conversions.append(rate)

        if daily_conversions:
            avg_conversion = sum(daily_conversions) / len(daily_conversions)
            if avg_conversion > 0 and today_conversion < avg_conversion * 0.8:
                drop_pct = round((1 - today_conversion / avg_conversion) * 100, 1)
                anomalies.append(Anomaly(
                    anomaly_type=AnomalyType.CONVERSION_DROP,
                    severity=Severity.WARN if drop_pct < 40 else Severity.CRITICAL,
                    description=f"Today's conversion rate ({today_conversion:.1%}) is {drop_pct}% below the 7-day average ({avg_conversion:.1%})",
                    suggested_action="Review store staffing levels and product availability. Check if any promotions are not being communicated effectively",
                    detected_at=now,
                ))

        # ── 3. DEAD_ZONE ───────────────────────────────────────────────
        # Find zones with 0 visits in last 30 minutes
        thirty_min_ago = (now - timedelta(minutes=30)).isoformat()

        # Get all known zones for this store
        cursor = await db.execute(
            """SELECT DISTINCT zone_id
               FROM events
               WHERE store_id = ?
                 AND zone_id IS NOT NULL
                 AND DATE(timestamp) = ?""",
            (store_id, today),
        )
        all_zones = {r["zone_id"] for r in await cursor.fetchall()}

        # Get zones with recent activity
        cursor = await db.execute(
            """SELECT DISTINCT zone_id
               FROM events
               WHERE store_id = ?
                 AND zone_id IS NOT NULL
                 AND timestamp >= ?""",
            (store_id, thirty_min_ago),
        )
        active_zones = {r["zone_id"] for r in await cursor.fetchall()}

        dead_zones = all_zones - active_zones
        for zone in dead_zones:
            anomalies.append(Anomaly(
                anomaly_type=AnomalyType.DEAD_ZONE,
                severity=Severity.INFO,
                description=f"Zone '{zone}' has had no customer visits in the last 30 minutes",
                suggested_action=f"Consider repositioning promotional displays in {zone} or deploying staff to engage customers",
                detected_at=now,
            ))

        return AnomalyResponse(store_id=store_id, anomalies=anomalies)

    finally:
        await db.close()
