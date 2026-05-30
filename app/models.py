"""
Pydantic models for the Store Intelligence API.
Defines event schemas, API request/response models, and enums.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


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
    """Single event conforming to the PRD event schema."""
    event_id: str = Field(..., description="UUID v4 — must be globally unique")
    store_id: str = Field(..., description="Store identifier from store_layout")
    camera_id: str = Field(..., description="Camera that produced this event")
    visitor_id: str = Field(..., description="Re-ID token — unique per visit session")
    event_type: EventType = Field(..., description="Type of behavioural event")
    timestamp: datetime = Field(..., description="ISO-8601 UTC timestamp")
    zone_id: Optional[str] = Field(None, description="Zone name; null for ENTRY/EXIT")
    dwell_ms: int = Field(0, ge=0, description="Duration in ms; 0 for instantaneous")
    is_staff: bool = Field(False, description="Whether this person is store staff")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence")
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        try:
            uuid.UUID(v, version=4)
        except ValueError:
            raise ValueError(f"event_id must be a valid UUID v4, got: {v}")
        return v


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
    avg_dwell_ms: float
    visit_count: int


class MetricsResponse(BaseModel):
    store_id: str
    date: str
    unique_visitors: int = 0
    conversion_rate: float = 0.0
    total_purchases: int = 0
    avg_dwell_by_zone: list[ZoneDwell] = Field(default_factory=list)
    current_queue_depth: int = 0
    abandonment_rate: float = 0.0


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
    visit_count: int
    avg_dwell_ms: float
    normalised_score: float = Field(..., ge=0, le=100)


class HeatmapResponse(BaseModel):
    store_id: str
    data_confidence: str = "normal"  # "low" if < 20 sessions
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
    status: str = "OK"  # OK | STALE_FEED


class HealthResponse(BaseModel):
    status: str = "healthy"
    uptime_seconds: float = 0.0
    stores: list[StoreHealth] = Field(default_factory=list)
    database: str = "connected"
