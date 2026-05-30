# Architecture Design — Store Intelligence API

## System Overview

The Store Intelligence system transforms raw CCTV footage from Purplle's Brigade Road (Bangalore) retail store into actionable business analytics. The system answers the fundamental question: **"How many people walked in, what did they do, and how many bought something?"**

The architecture follows a four-stage pipeline:

```
📹 CCTV Clips → 🔍 Detection Pipeline → ⚡ Event Stream → 🧠 Intelligence API → 📊 Live Dashboard
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Detection Pipeline (Offline)                  │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐  │
│  │ YOLOv8m  │───▶│ByteTrack │───▶│  Zone    │───▶│  Event    │  │
│  │ Person   │    │ Tracking │    │ Classify │    │  Emitter  │  │
│  │ Detector │    │ + Re-ID  │    │ + Staff  │    │  (JSONL)  │  │
│  └──────────┘    └──────────┘    └──────────┘    └─────┬─────┘  │
│       ▲                                                │        │
│       │                                                ▼        │
│  ┌────┴─────┐                                    ┌───────────┐  │
│  │ CAM 1-5  │                                    │ events.   │  │
│  │ .mp4     │                                    │ jsonl     │  │
│  └──────────┘                                    └─────┬─────┘  │
└────────────────────────────────────────────────────────┼────────┘
                                                         │
                           HTTP POST /events/ingest      │
                                                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                Intelligence API (Docker Container)               │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    FastAPI Application                     │  │
│  │                                                           │  │
│  │  POST /events/ingest ──▶ Validate ──▶ Dedup ──▶ Store    │  │
│  │                                                           │  │
│  │  GET /stores/{id}/metrics   ──▶ Real-time computation    │  │
│  │  GET /stores/{id}/funnel    ──▶ Session-based funnel     │  │
│  │  GET /stores/{id}/heatmap   ──▶ Zone activity heatmap    │  │
│  │  GET /stores/{id}/anomalies ──▶ Anomaly detection        │  │
│  │  GET /health                ──▶ Service health           │  │
│  │  GET /dashboard             ──▶ Web UI (SSE)             │  │
│  └────────────────────┬──────────────────────────────────────┘  │
│                       │                                          │
│                       ▼                                          │
│              ┌────────────────┐                                  │
│              │  SQLite (WAL)  │                                  │
│              │  events table  │                                  │
│              │  pos_txn table │                                  │
│              └────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Detection Pipeline (`pipeline/`)

The pipeline processes 4 customer-facing cameras (CAM 1, 2, 3, 5 — CAM 4 is a stockroom and is excluded):

| Camera | View | Purpose | Zones Detected |
|--------|------|---------|----------------|
| CAM 1 | Skincare wall | Floor zone tracking | SKINCARE, KOREAN_BEAUTY, CLEAN_BEAUTY |
| CAM 2 | Makeup wall + Accessories | Floor zone tracking | MAKEUP, ACCESSORIES, FRAGRANCE |
| CAM 3 | Store entrance (glass door) | Entry/exit counting | ENTRY |
| CAM 5 | Cash counter + Accessories | Billing queue tracking | BILLING, CASH_COUNTER |

**Processing flow per camera:**
1. **Detection**: YOLOv8m detects persons (class 0) at full 1080p
2. **Tracking**: ByteTrack assigns persistent IDs across frames with extended track buffer (90 frames ≈ 3s)
3. **Zone classification**: Spatial heuristics map person position → zone based on camera FOV and store layout
4. **Entry/Exit**: For CAM 3, vertical movement direction determines entry (upward) vs exit (downward)
5. **Staff classification**: Persons present for >50% of clip duration or appearing in 3+ zones are flagged as staff
6. **Event emission**: Structured events written to JSONL and POSTed to the API in batches of 100

**Key design decisions in the pipeline:**
- **Frame skipping**: Process every 2nd frame (effective 15fps) to double throughput without losing tracking fidelity
- **Low-confidence inclusion**: Events with confidence < 0.3 are still emitted but flagged — suppressing them would silently lose data
- **Zone classification by spatial heuristics**: Rather than training a zone classifier, I use the known camera mounting positions and store layout to map pixel coordinates to zones. This is deterministic and doesn't require additional training data.

### 2. Intelligence API (`app/`)

**Technology**: FastAPI with async SQLite (aiosqlite) and WAL mode for concurrent reads.

**Key endpoints:**

- **POST /events/ingest**: Batch ingestion with idempotency (INSERT OR IGNORE by event_id). Accepts up to 500 events. Returns partial success — valid events are stored even if some fail validation.

- **GET /stores/{id}/metrics**: Real-time computation of unique visitors, conversion rate, dwell times, queue depth, and abandonment rate. Staff events are excluded via `is_staff = 0` filter. Conversion rate uses the 5-minute POS correlation window.

- **GET /stores/{id}/funnel**: Session-based funnel (Entry → Zone Visit → Billing → Purchase) using `COUNT(DISTINCT visitor_id)`. REENTRY events are included in the Entry stage query but deduplicated by visitor_id.

- **GET /stores/{id}/anomalies**: Three anomaly types detected in real-time:
  - `BILLING_QUEUE_SPIKE`: Current queue depth ≥ 2× daily average
  - `CONVERSION_DROP`: Today's conversion < 80% of 7-day rolling average
  - `DEAD_ZONE`: Any zone with zero visits in the last 30 minutes

### 3. Production Readiness

- **Structured logging**: JSON-formatted logs with trace_id, store_id, endpoint, latency_ms, status_code on every request
- **Graceful degradation**: Database failures return HTTP 503 with structured error body, never raw stack traces
- **Health endpoint**: Reports per-store last-event timestamps with STALE_FEED warnings for >10 minute lag
- **Docker**: Single `docker compose up` starts the API with persistent SQLite volume

### 4. Live Dashboard

Web-based dashboard using Server-Sent Events (SSE) for real-time updates every 2 seconds. Displays:
- KPI cards (visitors, conversion rate, purchases, event count)
- Conversion funnel with animated bars and drop-off percentages
- Zone heatmap with color-coded activity levels
- Anomaly alerts with severity badges and suggested actions
- Live event feed showing recent detections

---

## AI-Assisted Decisions

### 1. Detection Model Selection — YOLOv8m vs YOLOv8n

**What AI suggested**: When I asked for the optimal model for retail person detection at 1080p/30fps, the LLM recommended YOLOv8n (nano) for maximum speed, arguing that in a take-home challenge, processing speed matters more than marginal accuracy gains.

**What I chose**: YOLOv8m (medium). **I disagreed with the AI's recommendation.**

**Why**: After examining the actual footage, I observed that the cameras capture oblique angles with significant occlusion (people behind product displays). The nano model's smaller feature maps struggle with these partially-visible detections. The medium model's 2-3× longer inference time is acceptable because:
- The clips are only ~2.5 minutes each (not 20 minutes as the PRD template suggested)
- Batch processing is fine — we don't need real-time FPS
- Accuracy on group detection (separating 2-3 people entering together) is critical for the conversion rate metric

### 2. SQLite vs PostgreSQL for Storage

**What AI suggested**: PostgreSQL with connection pooling for "production-grade" durability and concurrent write handling.

**What I chose**: SQLite with WAL mode. **I partially agreed but chose differently for the challenge context.**

**Why**: For a single-store system evaluated on a reviewer's machine, SQLite eliminates an entire service dependency. `docker compose up` just works — no PostgreSQL container to pull, no initialization delay, no connection string configuration. WAL mode gives us concurrent read access (multiple GET endpoints) while maintaining single-writer consistency. The trade-off is clear: at 40 live stores (as the PRD mentions for follow-up questions), SQLite would need to be replaced. I document this in CHOICES.md as a scaling decision.

### 3. Staff Detection — Classifier vs Heuristic

**What AI suggested**: Train a lightweight classifier on upper-body crops using color histograms of the staff uniform, or use a Vision-Language Model (VLM) to identify staff.

**What I chose**: A two-signal heuristic approach. **I took the AI's color histogram idea but rejected the VLM approach.**

**Why**: The VLM approach would add significant latency and an API dependency to the pipeline. Instead, I use two observable signals that reliably separate staff from customers:
1. **Temporal presence**: Staff are present for >50% of the clip duration; customers visit briefly
2. **Zone coverage**: Staff traverse 3+ zones; customers typically visit 1-2 zones

This heuristic is imperfect — it would misclassify a very long-browsing customer as staff. But in a 2.5-minute clip, any person visible for >75 seconds across multiple zones is almost certainly staff. The approach is explainable and doesn't require additional model weights.
