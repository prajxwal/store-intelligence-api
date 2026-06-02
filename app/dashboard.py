"""
Dashboard — SSE endpoint for real-time metric streaming + static file serving.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from app.database import get_db

logger = logging.getLogger("store_intelligence")
router = APIRouter()


async def _get_dashboard_data(store_id: str) -> dict:
    """Fetch current metrics for SSE streaming."""
    try:
        db = await get_db()
        try:
            # Quick metrics snapshot
            cursor = await db.execute(
                """SELECT COUNT(DISTINCT visitor_id) as visitors
                   FROM events
                   WHERE store_id = ? AND is_staff = 0 AND event_type = 'entry'""",
                (store_id,),
            )
            row = await cursor.fetchone()
            visitors = row["visitors"] if row else 0

            # POS purchases — only show if pipeline has produced events
            purchases = 0
            if visitors > 0:
                cursor = await db.execute(
                    """SELECT COUNT(DISTINCT order_time) as purchases
                       FROM pos_transactions WHERE store_id = ?""",
                    (store_id,),
                )
                row = await cursor.fetchone()
                purchases = row["purchases"] if row else 0

            conversion = round(purchases / visitors, 4) if visitors > 0 else 0.0

            cursor = await db.execute(
                """SELECT COUNT(*) as total FROM events WHERE store_id = ?""",
                (store_id,),
            )
            row = await cursor.fetchone()
            total_events = row["total"] if row else 0

            # Zone breakdown
            cursor = await db.execute(
                """SELECT zone_id, COUNT(DISTINCT visitor_id) as cnt, AVG(dwell_ms) as avg_dwell
                   FROM events
                   WHERE store_id = ? AND is_staff = 0 AND zone_id IS NOT NULL
                   GROUP BY zone_id ORDER BY cnt DESC""",
                (store_id,),
            )
            zones = [
                {"zone_id": r["zone_id"], "visits": r["cnt"], "avg_dwell_ms": round(r["avg_dwell"] or 0)}
                for r in await cursor.fetchall()
            ]

            # Recent events
            cursor = await db.execute(
                """SELECT event_type, visitor_id, zone_id, timestamp, confidence
                   FROM events WHERE store_id = ?
                   ORDER BY timestamp DESC LIMIT 10""",
                (store_id,),
            )
            recent = [
                {
                    "event_type": r["event_type"],
                    "visitor_id": r["visitor_id"],
                    "zone_id": r["zone_id"],
                    "timestamp": r["timestamp"],
                    "confidence": r["confidence"],
                }
                for r in await cursor.fetchall()
            ]

            # Gender split
            cursor = await db.execute(
                """SELECT gender_pred, COUNT(DISTINCT visitor_id) as cnt
                   FROM events
                   WHERE store_id = ? AND event_type = 'entry' AND is_staff = 0
                   GROUP BY gender_pred""",
                (store_id,),
            )
            gender = {"male": 0, "female": 0, "unknown": 0}
            for r in await cursor.fetchall():
                g = r["gender_pred"]
                if g == "M":
                    gender["male"] = r["cnt"]
                elif g == "F":
                    gender["female"] = r["cnt"]
                else:
                    gender["unknown"] = r["cnt"]

            # Top brands
            cursor = await db.execute(
                """SELECT brand_name, SUM(total_amount) as revenue
                   FROM pos_transactions
                   WHERE store_id = ? AND brand_name IS NOT NULL AND brand_name != ''
                   GROUP BY brand_name ORDER BY revenue DESC LIMIT 5""",
                (store_id,),
            )
            top_brands = [
                {"brand": r["brand_name"], "revenue": round(r["revenue"], 2)}
                for r in await cursor.fetchall()
            ]

            return {
                "store_id": store_id,
                "unique_visitors": visitors,
                "total_purchases": purchases,
                "conversion_rate": conversion,
                "total_events": total_events,
                "zones": zones,
                "recent_events": recent,
                "gender_split": gender,
                "top_brands": top_brands,
            }
        finally:
            await db.close()
    except Exception as e:
        logger.error(f"Dashboard data fetch error: {e}")
        return {"error": str(e)}


@router.get("/dashboard/stream")
async def dashboard_stream(request: Request, store_id: str = "ST1008"):
    """SSE endpoint streaming real-time metrics every 2 seconds."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            data = await _get_dashboard_data(store_id)
            yield {"event": "metrics", "data": json.dumps(data)}
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the dashboard HTML page."""
    dashboard_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "dashboard", "index.html"
    )
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)
