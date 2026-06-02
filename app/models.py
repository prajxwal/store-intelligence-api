"""
Pydantic models for the Store Intelligence API.
Aligned with Purplle's expected event schema (sample_events.jsonl).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    """Event types matching Purplle's sample_events schema (lowercase)."""
    entry = "entry"
    exit = "exit"
    zone_entered = "zone_entered"
    zone_exited = "zone_exited"
    zone_dwell = "zone_dwell"
    queue_completed = "queue_completed"
    queue_abandoned = "queue_abandoned"
    reentry = "reentry"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class AnomalyType(str, Enum):
    BILLING_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
    CONVERSION_DROP = "CONVERSION_DROP"
    DEAD_ZONE = "DEAD_ZONE"


# ─── Event Models ─────────────────────────────────────────────────────────────

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None


class EventIngest(BaseModel):
    """Single event conforming to the Purplle event schema."""
    # Core identifiers
    event_id: Optional[str] = Field(None, description="UUID v4 — globally unique (alias: queue_event_id)")
    queue_event_id: Optional[str] = Field(None, description="UUID for queue events")
    store_id: Optional[str] = Field(None, description="Store identifier")
    store_code: Optional[str] = Field(None, description="Store code (entry/exit events)")
    camera_id: str = Field(..., description="Camera that produced this event")

    # Visitor tracking
    visitor_id: Optional[str] = Field(None, description="Re-ID token (alias: id_token)")
    id_token: Optional[str] = Field(None, description="Visitor ID for entry/exit events")
    track_id: Optional[int] = Field(None, description="ByteTrack tracker ID")

    # Event data
    event_type: EventType = Field(..., description="Type of behavioural event")
    timestamp: Optional[datetime] = Field(None, description="ISO-8601 timestamp")
    event_timestamp: Optional[str] = Field(None, description="Timestamp for entry/exit events")
    event_time: Optional[str] = Field(None, description="Timestamp for zone events")

    # Zone fields
    zone_id: Optional[str] = Field(None, description="Zone identifier")
    zone_name: Optional[str] = Field(None, description="Human-readable zone name")
    zone_type: Optional[str] = Field(None, description="SHELF | DISPLAY | BILLING")
    is_revenue_zone: Optional[str] = Field(None, description="Yes | No")
    zone_hotspot_x: Optional[float] = Field(None, description="Detection centroid X")
    zone_hotspot_y: Optional[float] = Field(None, description="Detection centroid Y")

    # Dwell / duration
    dwell_ms: int = Field(0, ge=0, description="Duration in ms; 0 for instantaneous")

    # Staff flag
    is_staff: bool = Field(False, description="Whether this person is store staff")

    # Detection confidence
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Detection confidence")

    # Demographics (from face analysis — nullable)
    gender_pred: Optional[str] = Field(None, description="M | F | null")
    age_pred: Optional[int] = Field(None, description="Estimated age")
    age_bucket: Optional[str] = Field(None, description="18-24, 25-34, 35-44, etc.")
    is_face_hidden: Optional[bool] = Field(None, description="Face not visible")

    # Group detection
    group_id: Optional[str] = Field(None, description="Group identifier")
    group_size: Optional[int] = Field(None, description="Number in group")

    # Queue timing fields
    queue_join_ts: Optional[str] = Field(None, description="When person joined queue")
    queue_served_ts: Optional[str] = Field(None, description="When person reached counter")
    queue_exit_ts: Optional[str] = Field(None, description="When person left queue area")
    wait_seconds: Optional[int] = Field(None, description="Total wait time in seconds")
    queue_position_at_join: Optional[int] = Field(None, description="Position when joining")
    abandoned: Optional[bool] = Field(None, description="True if left without purchase")

    # Legacy metadata
    metadata: Optional[EventMetadata] = Field(default_factory=EventMetadata)

    @field_validator("event_id", mode="before")
    @classmethod
    def validate_event_id(cls, v):
        if v is None:
            return v
        try:
            uuid.UUID(str(v), version=4)
        except ValueError:
            raise ValueError(f"event_id must be a valid UUID v4, got: {v}")
        return str(v)

    def get_effective_id(self) -> str:
        """Return the best available event identifier."""
        return self.event_id or self.queue_event_id or str(uuid.uuid4())

    def get_effective_store(self) -> str:
        """Return the best available store identifier."""
        return self.store_id or self.store_code or "UNKNOWN"

    def get_effective_visitor(self) -> str:
        """Return the best available visitor identifier."""
        return self.visitor_id or self.id_token or (f"TRK_{self.track_id}" if self.track_id else "UNKNOWN")

    def get_effective_timestamp(self) -> str:
        """Return the best available timestamp as ISO string."""
        if self.timestamp:
            return self.timestamp.isoformat()
        return self.event_timestamp or self.event_time or datetime.utcnow().isoformat()


class EventBatch(BaseModel):
    """Batch of events for ingestion (max 500)."""
    events: list[EventIngest] = Field(..., max_length=500)


# ─── Ingest Response ──────────────────────────────────────────────────────────

class EventError(BaseModel):
    index: int
    event_id: Optional[str] = None
    error: str


class IngestResponse(BaseModel):
    accepted: int = 0
    rejected: int = 0
    errors: list[EventError] = Field(default_factory=list)


# ─── Metrics Response ─────────────────────────────────────────────────────────

class ZoneDwell(BaseModel):
    zone_id: str
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    avg_dwell_ms: float
    visit_count: int


class GenderSplit(BaseModel):
    male: int = 0
    female: int = 0
    unknown: int = 0


class AgeBucketCount(BaseModel):
    bucket: str
    count: int


class MetricsResponse(BaseModel):
    store_id: str
    date: str
    unique_visitors: int = 0
    conversion_rate: float = 0.0
    total_purchases: int = 0
    total_events: int = 0
    avg_dwell_by_zone: list[ZoneDwell] = Field(default_factory=list)
    current_queue_depth: int = 0
    avg_wait_seconds: float = 0.0
    abandonment_rate: float = 0.0
    gender_split: Optional[GenderSplit] = None
    age_distribution: list[AgeBucketCount] = Field(default_factory=list)
    top_brands: list[dict] = Field(default_factory=list)


# ─── Funnel Response ──────────────────────────────────────────────────────────

class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float = 0.0


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage] = Field(default_factory=list)


# ─── Heatmap Response ─────────────────────────────────────────────────────────

class ZoneHeat(BaseModel):
    zone_id: str
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    visit_count: int
    avg_dwell_ms: float
    normalised_score: float = Field(..., ge=0, le=100)


class HeatmapResponse(BaseModel):
    store_id: str
    data_confidence: str = "normal"
    zones: list[ZoneHeat] = Field(default_factory=list)


# ─── Anomaly Response ─────────────────────────────────────────────────────────

class Anomaly(BaseModel):
    anomaly_type: AnomalyType
    severity: Severity
    description: str
    suggested_action: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly] = Field(default_factory=list)


# ─── Health Response ──────────────────────────────────────────────────────────

class StoreHealth(BaseModel):
    store_id: str
    last_event_at: Optional[datetime] = None
    event_count: int = 0
    status: str = "OK"


class HealthResponse(BaseModel):
    status: str = "healthy"
    uptime_seconds: float = 0.0
    stores: list[StoreHealth] = Field(default_factory=list)
    database: str = "connected"
