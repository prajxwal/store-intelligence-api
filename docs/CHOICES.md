# Technical Choices — Store Intelligence API

This document explains three key architectural decisions, the options considered, what AI tools suggested, and what I ultimately chose and why.

---

## Decision 1: Detection Model — YOLOv8m

### Context
The detection pipeline needs to identify and track individual people in retail CCTV footage at 1080p resolution. The footage includes edge cases: groups entering together, partial occlusion behind displays, and varying lighting conditions.

### Options Considered

| Model | Inference Speed (1080p) | mAP₅₀ (COCO) | Key Trade-off |
|-------|------------------------|---------------|---------------|
| YOLOv8n (nano) | ~8ms/frame | 37.3 | Fastest, but misses occluded people |
| YOLOv8s (small) | ~15ms/frame | 44.9 | Good balance for real-time |
| **YOLOv8m (medium)** | ~30ms/frame | 50.2 | Best accuracy for batch processing |
| YOLOv8x (xlarge) | ~80ms/frame | 53.9 | Overkill, diminishing returns |
| RT-DETR | ~40ms/frame | 54.8 | Transformer-based, no NMS needed, higher GPU memory |

### What AI Suggested
I used Claude to evaluate the model options for retail-specific scenarios. The AI recommended **YOLOv8n** with the reasoning that:
- The challenge is time-constrained, so fast processing helps iterate
- Tracking (ByteTrack) compensates for missed detections by interpolating
- Nano is "good enough" for person detection which is a well-represented class

### What I Chose and Why
I chose **YOLOv8m** because after examining the actual footage:

1. **Group entry is the hardest problem**: When 2-3 people walk through the glass door together (CAM 3), their bounding boxes overlap. The medium model's larger feature maps resolve these overlapping detections better — tested on sample frames, nano detected 1 person where medium correctly detected 2.

2. **Processing time is not a bottleneck**: The total footage is ~12 minutes across 5 cameras. Even at 30ms/frame, the entire pipeline completes in under 10 minutes. There's no real-time requirement for batch processing.

3. **Accuracy directly impacts the north star metric**: Every missed person inflates the conversion rate (fewer visitors → higher apparent conversion). The medium model's +13 mAP points translates to meaningfully better visitor counts.

4. **I rejected RT-DETR** despite its higher accuracy because: the Ultralytics integration for ByteTrack tracking is more mature with YOLO, and RT-DETR's transformer architecture requires significantly more GPU memory, making it harder to run on the reviewer's machine.

---

## Decision 2: Event Schema Design

### Context
The detection pipeline must emit structured events that support all downstream analytics queries: conversion rate, funnel analysis, zone heatmaps, queue tracking, and anomaly detection. The schema must handle edge cases (re-entry, staff, partial occlusion) without losing information.

### Options Considered

**Option A — Minimal schema (position-based)**
```json
{"person_id": "...", "x": 450, "y": 200, "frame": 1234, "camera": "CAM_01"}
```
Raw position data. All business logic computed downstream. Simple but pushes complexity to the API.

**Option B — Business-event schema (chosen)**
```json
{"event_type": "ZONE_DWELL", "visitor_id": "VIS_0001", "zone_id": "SKINCARE", "dwell_ms": 45000, ...}
```
Pre-computed business events. Pipeline does the heavy lifting. API just aggregates.

**Option C — Hybrid (positions + events)**
Both raw positions and derived events. Maximum flexibility but doubles storage and adds complexity.

### What AI Suggested
The AI recommended **Option C (hybrid)** — storing raw positions for future reprocessing while also emitting business events for immediate use. The argument was that raw data enables retrospective analysis with new zone definitions.

### What I Chose and Why
I chose **Option B (business-event schema)** because:

1. **The PRD explicitly defines the schema**: The event types (ENTRY, EXIT, ZONE_DWELL, BILLING_QUEUE_JOIN, etc.) are specified. Following the given schema ensures compatibility with the scoring harness.

2. **The confidence field preserves uncertainty**: Rather than discarding low-confidence detections, the schema includes a `confidence` float. This means the API can always filter by confidence threshold without losing information — achieving the benefit the AI wanted from raw data.

3. **Storage efficiency matters for SQLite**: Storing raw positions at 15fps across 4 cameras would generate ~3,600 rows/minute. Business events generate ~5-20 events per visitor journey. The 100× reduction keeps SQLite fast.

4. **The `metadata` field is extensible**: `queue_depth`, `sku_zone`, and `session_seq` in the metadata object allow future enrichment without schema changes.

The key schema design choice was making `session_seq` an ordinal within each visitor's journey. This enables funnel reconstruction from events alone — you can order a visitor's events by session_seq to trace their path through the store.

---

## Decision 3: API Storage — SQLite with WAL Mode

### Context
The API needs to store events, compute real-time metrics, and serve multiple concurrent GET requests. It must start with `docker compose up` without external dependencies.

### Options Considered

| Storage | Pros | Cons |
|---------|------|------|
| **SQLite + WAL** | Zero-config, single file, fast reads | Single-writer, no network access |
| PostgreSQL | Full ACID, concurrent writes, production standard | Extra Docker container, init scripts, connection config |
| DuckDB | Columnar analytics, fast aggregations | Less mature for OLTP, no concurrent writes |
| Redis + SQLite | Fast cache for metrics, persistent store for events | Two systems to manage |

### What AI Suggested
The AI recommended **PostgreSQL** as the "production-ready" choice, arguing that:
- It handles concurrent writes from multiple pipeline instances
- It's the industry standard for analytics workloads
- Connection pooling with asyncpg gives excellent async performance

### What I Chose and Why
I chose **SQLite with WAL mode** for these specific reasons:

1. **Single-command startup**: The acceptance gate requires `docker compose up` to work without manual intervention. SQLite eliminates a PostgreSQL container, its healthcheck delay, and migration timing issues. The API is ready in <1 second.

2. **Read concurrency is solved by WAL**: Write-Ahead Logging allows multiple concurrent readers while one writer operates. Since the API's read endpoints (metrics, funnel, heatmap, anomalies) are the hot path, and writes (ingest) are batched, WAL mode is sufficient.

3. **Scale is bounded**: This is a single-store system processing ~12 minutes of footage. The total event count is in the low thousands. SQLite handles millions of rows efficiently — we're nowhere near its limits.

4. **I documented the scaling boundary**: In a follow-up interview question about scaling to 40 stores, the answer is straightforward: replace SQLite with PostgreSQL, add connection pooling, and introduce a message queue (Redis/Kafka) between ingest and storage. The current architecture's clean separation between ingestion and query endpoints makes this a targeted change, not a rewrite.

5. **Reviewer experience**: Evaluators spend 2 minutes running the system. A fast, zero-config startup creates a better first impression than a slow PostgreSQL initialization followed by migration scripts.

### What I Would Change at Scale
At 40 stores with real-time event streaming:
- **Storage**: PostgreSQL with TimescaleDB extension for time-series queries
- **Ingest buffer**: Redis Streams or Kafka for decoupling pipeline from API
- **Caching**: Redis for hot metrics (conversion rate updated every 10s)
- **Connection pooling**: asyncpg with pool size tuned to worker count
