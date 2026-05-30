"""
Event emission — creates structured events conforming to the PRD schema.
Generates UUID4 event_ids, derives timestamps from video frame offsets.
Outputs to JSONL file and optionally POSTs to the API.
"""

from __future__ import annotations

import json
import os
import uuid
import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional

from pipeline.config import OUTPUT_DIR, API_URL, STORE_ID

logger = logging.getLogger("pipeline")


class EventEmitter:
    """Emits structured events to file and API."""

    def __init__(self, store_id: str = STORE_ID, output_dir: str = OUTPUT_DIR):
        self.store_id = store_id
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        self.output_file = os.path.join(output_dir, "events.jsonl")
        self.event_buffer: list[dict] = []
        self.buffer_size = 100  # Batch size for API submission
        self.total_emitted = 0
        self.session_sequences: dict[str, int] = {}  # visitor_id -> seq counter

    def _next_seq(self, visitor_id: str) -> int:
        """Get next session sequence number for a visitor."""
        self.session_sequences.setdefault(visitor_id, 0)
        self.session_sequences[visitor_id] += 1
        return self.session_sequences[visitor_id]

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
        """Create a single event conforming to the PRD schema."""
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

        # Write to file immediately
        with open(self.output_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Batch submit to API when buffer is full
        if len(self.event_buffer) >= self.buffer_size:
            self.flush_to_api()

    def flush_to_api(self):
        """Send buffered events to the API."""
        if not self.event_buffer:
            return

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{API_URL}/events/ingest",
                    json={"events": self.event_buffer},
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
