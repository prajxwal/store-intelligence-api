"""
Event emission — creates structured events matching Purplle's sample schema.
Generates UUID4 event_ids, derives timestamps from video frame offsets.
Outputs to JSONL file and optionally POSTs to the API.
"""

from __future__ import annotations

import json
import os
import uuid
import logging
import httpx
from datetime import datetime
from typing import Optional

from pipeline.config import OUTPUT_DIR, API_URL, STORE_ID, STORE_CODE, ZONE_METADATA

logger = logging.getLogger("pipeline")


# Zone ID format: PURPLLE_BLR_1008_Z{nn}
_zone_counter = 0
_zone_id_cache: dict[str, str] = {}


def _get_zone_id(zone_name: str) -> str:
    """Generate a Purplle-format zone ID."""
    global _zone_counter
    if zone_name not in _zone_id_cache:
        _zone_counter += 1
        _zone_id_cache[zone_name] = f"PURPLLE_BLR_1008_Z{_zone_counter:02d}"
    return _zone_id_cache[zone_name]


class EventEmitter:
    """Emits structured events matching Purplle's expected format."""

    def __init__(self, store_id: str = STORE_ID, output_dir: str = OUTPUT_DIR):
        self.store_id = store_id
        self.store_code = STORE_CODE
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self.output_file = os.path.join(output_dir, "events.jsonl")
        self.event_buffer: list[dict] = []
        self.buffer_size = 100
        self.total_emitted = 0
        self.session_sequences: dict[str, int] = {}
        self._visitor_counter = 0

    def next_visitor_id(self) -> str:
        """Generate visitor ID in Purplle's format: ID_60001."""
        self._visitor_counter += 1
        return f"ID_{60000 + self._visitor_counter}"

    def _next_seq(self, visitor_id: str) -> int:
        self.session_sequences.setdefault(visitor_id, 0)
        self.session_sequences[visitor_id] += 1
        return self.session_sequences[visitor_id]

    def create_entry_exit_event(
        self,
        camera_id: str,
        visitor_id: str,
        event_type: str,  # "entry" or "exit"
        timestamp: datetime,
        is_staff: bool = False,
        confidence: float = 0.5,
        gender_pred: Optional[str] = None,
        age_pred: Optional[int] = None,
        age_bucket: Optional[str] = None,
        is_face_hidden: bool = False,
        group_id: Optional[str] = None,
        group_size: Optional[int] = None,
    ) -> dict:
        """Create entry/exit event matching Purplle's sample schema."""
        return {
            "event_type": event_type,
            "id_token": visitor_id,
            "store_code": self.store_code,
            "camera_id": camera_id.lower(),
            "event_timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "is_staff": is_staff,
            "gender_pred": gender_pred,
            "age_pred": age_pred,
            "age_bucket": age_bucket,
            "is_face_hidden": is_face_hidden,
            "group_id": group_id,
            "group_size": group_size,
        }

    def create_zone_event(
        self,
        camera_id: str,
        track_id: int,
        event_type: str,  # "zone_entered" or "zone_exited"
        timestamp: datetime,
        zone: str,
        hotspot_x: float = 0.0,
        hotspot_y: float = 0.0,
        confidence: float = 0.5,
        gender_pred: Optional[str] = None,
        age_pred: Optional[int] = None,
        age_bucket: Optional[str] = None,
    ) -> dict:
        """Create zone event matching Purplle's sample schema."""
        meta = ZONE_METADATA.get(zone, {})
        return {
            "event_type": event_type,
            "track_id": track_id,
            "store_id": self.store_id,
            "camera_id": camera_id,
            "zone_id": _get_zone_id(zone),
            "zone_name": meta.get("zone_name", zone),
            "zone_type": meta.get("zone_type", "SHELF"),
            "is_revenue_zone": meta.get("is_revenue_zone", "Yes"),
            "event_time": timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "zone_hotspot_x": round(hotspot_x, 1),
            "zone_hotspot_y": round(hotspot_y, 1),
            "gender": gender_pred,
            "age": age_pred,
            "age_bucket": age_bucket,
        }

    def create_queue_event(
        self,
        camera_id: str,
        track_id: int,
        event_type: str,  # "queue_completed" or "queue_abandoned"
        zone: str,
        queue_join_ts: datetime,
        queue_exit_ts: datetime,
        queue_served_ts: Optional[datetime] = None,
        wait_seconds: int = 0,
        queue_position_at_join: int = 1,
        abandoned: bool = False,
        hotspot_x: float = 0.0,
        hotspot_y: float = 0.0,
        gender_pred: Optional[str] = None,
        age_pred: Optional[int] = None,
        age_bucket: Optional[str] = None,
    ) -> dict:
        """Create queue event matching Purplle's sample schema."""
        meta = ZONE_METADATA.get(zone, ZONE_METADATA.get("BILLING", {}))
        billing_zone_id = _get_zone_id("BILLING_QUEUE")
        return {
            "queue_event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "track_id": track_id,
            "store_id": self.store_id,
            "camera_id": camera_id,
            "zone_id": billing_zone_id,
            "zone_name": "Billing Counter Queue",
            "zone_type": "BILLING",
            "is_revenue_zone": "Yes",
            "queue_join_ts": queue_join_ts.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "queue_served_ts": queue_served_ts.strftime("%Y-%m-%dT%H:%M:%S.%f") if queue_served_ts else None,
            "queue_exit_ts": queue_exit_ts.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "wait_seconds": wait_seconds,
            "queue_position_at_join": queue_position_at_join,
            "abandoned": abandoned,
            "zone_hotspot_x": round(hotspot_x, 1),
            "zone_hotspot_y": round(hotspot_y, 1),
            "gender": gender_pred,
            "age": age_pred,
            "age_bucket": age_bucket,
        }

    def create_event(
        self,
        camera_id: str,
        visitor_id: str,
        event_type: str,
        timestamp: datetime,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        is_staff: bool = False,
        confidence: float = 0.5,
        queue_depth: Optional[int] = None,
        sku_zone: Optional[str] = None,
    ) -> dict:
        """Legacy event creator — for API ingestion format."""
        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(confidence, 3),
            "metadata": {
                "queue_depth": queue_depth,
                "sku_zone": sku_zone or zone_id,
                "session_seq": self._next_seq(visitor_id),
            },
        }
        return event

    def emit(self, event: dict):
        """Buffer an event for output."""
        self.event_buffer.append(event)
        self.total_emitted += 1

        # Write to JSONL immediately
        with open(self.output_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Batch submit to API when buffer is full
        if len(self.event_buffer) >= self.buffer_size:
            self.flush_to_api()

    def flush_to_api(self):
        """Send buffered events to the API."""
        if not self.event_buffer:
            return

        # Convert events to API ingestion format
        api_events = []
        for ev in self.event_buffer:
            api_ev = self._to_api_format(ev)
            if api_ev:
                api_events.append(api_ev)

        if not api_events:
            self.event_buffer.clear()
            return

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{API_URL}/events/ingest",
                    json={"events": api_events},
                )
                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        f"API ingest: accepted={result.get('accepted', 0)}, "
                        f"rejected={result.get('rejected', 0)}"
                    )
                else:
                    logger.warning(f"API ingest failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"Could not reach API at {API_URL}: {e}")

        self.event_buffer.clear()

    def _to_api_format(self, event: dict) -> dict | None:
        """Convert a sample-format event to API ingestion format."""
        etype = event.get("event_type", "")

        # Determine event ID
        eid = event.get("event_id") or event.get("queue_event_id") or str(uuid.uuid4())

        # Determine store_id
        sid = event.get("store_id") or self.store_id

        # Determine visitor_id
        vid = event.get("visitor_id") or event.get("id_token") or f"TRK_{event.get('track_id', 0)}"

        # Determine timestamp
        ts = event.get("timestamp") or event.get("event_timestamp") or event.get("event_time") or ""

        return {
            "event_id": eid,
            "store_id": sid,
            "camera_id": event.get("camera_id", ""),
            "visitor_id": vid,
            "track_id": event.get("track_id"),
            "event_type": etype,
            "timestamp": ts,
            "zone_id": event.get("zone_id"),
            "zone_name": event.get("zone_name"),
            "zone_type": event.get("zone_type"),
            "is_revenue_zone": event.get("is_revenue_zone"),
            "zone_hotspot_x": event.get("zone_hotspot_x"),
            "zone_hotspot_y": event.get("zone_hotspot_y"),
            "dwell_ms": event.get("dwell_ms", 0),
            "is_staff": event.get("is_staff", False),
            "confidence": event.get("confidence", 0.5),
            "gender_pred": event.get("gender_pred") or event.get("gender"),
            "age_pred": event.get("age_pred") or event.get("age"),
            "age_bucket": event.get("age_bucket"),
            "is_face_hidden": event.get("is_face_hidden"),
            "group_id": event.get("group_id"),
            "group_size": event.get("group_size"),
            "queue_join_ts": event.get("queue_join_ts"),
            "queue_served_ts": event.get("queue_served_ts"),
            "queue_exit_ts": event.get("queue_exit_ts"),
            "wait_seconds": event.get("wait_seconds"),
            "queue_position_at_join": event.get("queue_position_at_join"),
            "abandoned": event.get("abandoned"),
        }

    def finalize(self):
        """Flush remaining events and log summary."""
        self.flush_to_api()
        logger.info(f"Total events emitted: {self.total_emitted}")
        logger.info(f"Events written to: {self.output_file}")

    def get_stats(self) -> dict:
        return {
            "total_emitted": self.total_emitted,
            "unique_visitors": len(self.session_sequences),
            "output_file": self.output_file,
        }
