# 🏪 Store Intelligence API

**Real-time retail analytics from CCTV footage** — End-to-end system that transforms raw store camera feeds into actionable business metrics.

> **North Star Metric:** `Conversion Rate = Visitors who purchased ÷ Total unique visitors`

---

## 🚀 Quick Start

### Docker (One Command)

```bash
docker compose up --build
```

API → `http://localhost:8000` &nbsp;|&nbsp; Dashboard → `http://localhost:8000/dashboard` &nbsp;|&nbsp; Docs → `http://localhost:8000/docs`

### Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the API server
uvicorn app.main:app --reload --port 8000

# 3. Load POS transaction data
python -m pipeline.load_pos

# 4. Run detection pipeline (Store 1)
python -m pipeline.detect --store store1 --model yolov8m.pt

# 5. Run detection pipeline (Store 2)
python -m pipeline.detect --store store2 --model yolov8m.pt
```

---

## 🏗️ System Architecture

```
📹 CCTV Clips ──→ 🔍 YOLOv8m + ByteTrack ──→ ⚡ Structured Events ──→ 🧠 FastAPI ──→ 📊 Live Dashboard
   (5 cameras)       (Person detection &         (JSONL + API POST)      (SQLite WAL)    (SSE real-time)
                      tracking per frame)
```

| Layer | Technology | Purpose |
|---|---|---|
| **Detection** | YOLOv8m + ByteTrack | Person detection, tracking, zone classification |
| **Events** | Structured JSONL | 8 event types with UUID4 IDs, session sequences |
| **API** | FastAPI + aiosqlite (WAL) | 7 analytics endpoints with structured logging |
| **Dashboard** | Vanilla HTML/CSS/JS + SSE | Real-time metrics, funnel, heatmap, anomalies |
| **Container** | Docker Compose | Single-command deployment with persistent volume |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/events/ingest` | Batch event ingestion (max 500, idempotent) |
| `GET` | `/stores/{id}/metrics` | Conversion rate, dwell times, queue depth |
| `GET` | `/stores/{id}/funnel` | Entry → Zone → Billing → Purchase funnel |
| `GET` | `/stores/{id}/heatmap` | Zone activity heatmap (0–100 normalised) |
| `GET` | `/stores/{id}/anomalies` | Queue spikes, conversion drops, dead zones |
| `GET` | `/health` | Service health + per-store STALE_FEED detection |
| `GET` | `/dashboard` | Live web dashboard (SSE-powered) |

### Example Usage

```bash
# Check health
curl http://localhost:8000/health

# Ingest events
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d '{"events": [{"event_id": "550e8400-...", "store_id": "ST1008", "camera_id": "CAM_03", "visitor_id": "VIS_0001", "event_type": "ENTRY", "timestamp": "2026-04-10T20:10:00Z", "zone_id": null, "dwell_ms": 0, "is_staff": false, "confidence": 0.85, "metadata": {"queue_depth": null, "sku_zone": null, "session_seq": 1}}]}'

# Get store metrics
curl http://localhost:8000/stores/ST1008/metrics?target_date=2026-04-10

# Get conversion funnel
curl http://localhost:8000/stores/ST1008/funnel?target_date=2026-04-10

# Get zone heatmap
curl http://localhost:8000/stores/ST1008/heatmap?target_date=2026-04-10

# Get anomalies
curl http://localhost:8000/stores/ST1008/anomalies?target_date=2026-04-10
```

---

## 🎥 Detection Pipeline

### Camera Setup

**Store 1 — Brigade Bangalore (ST1008)** — 10/04/2026

| Camera | Resolution | FPS | View | Zones Detected |
|---|---|---|---|---|
| CAM 1 | 1920x1080 | 30 | Skincare wall (Korean, Face Shop, DermDoc) | `SKINCARE`, `KOREAN_BEAUTY`, `CLEAN_BEAUTY` |
| CAM 2 | 1920x1080 | 30 | Makeup wall (Lakme, Faces Canada, Maybelline) | `MAKEUP`, `ACCESSORIES`, `FRAGRANCE` |
| CAM 3 | 1920x1080 | 30 | Store entrance (glass door) | `ENTRY` -- Entry/Exit detection |
| CAM 5 | 1920x1080 | 25 | Cash counter + Accessories | `BILLING`, `CASH_COUNTER` |

**Store 2 — Purplle Store 2 (ST2001)** — 08/03/2026 & 29/03/2026

| Camera | Resolution | FPS | View | Zones Detected |
|---|---|---|---|---|
| Entry 1 | 960x1080 | 15 | Glass door entrance (top-down) | `ENTRY` -- Entry/Exit detection |
| Entry 2 | 960x1080 | 15 | Same entrance (different date) | `ENTRY` -- Entry/Exit detection |
| Zone | 960x1080 | 15 | Narrow aisle (skincare + haircare) | `SKINCARE`, `HAIRCARE` |
| Billing | 960x1080 | 15 | Cash counter (top-down) | `BILLING`, `CASH_COUNTER`, `MAKEUP` |

### Pipeline Processing Flow

```
Frame -> YOLOv8m (person detection)
      -> ByteTrack (persistent ID assignment)
      -> Zone Classification (spatial heuristics from store layout)
      -> Entry/Exit Detection (vertical movement on entry cameras)
      -> Staff Classification (presence >50% OR 3+ zones)
      -> Event Emission (UUID4, ISO-8601 timestamps, JSONL + API)
```

### Event Types

| Type | Trigger | Key Fields |
|---|---|---|
| `entry` | Person crosses door threshold inward | `visitor_id`, `confidence` |
| `exit` | Person crosses door threshold outward | `visitor_id`, `confidence` |
| `zone_entered` | Person enters a product zone | `zone_id`, `zone_name`, `zone_type` |
| `zone_exited` | Person leaves a product zone | `zone_id`, `dwell_ms` |
| `zone_dwell` | Person stays >30s in same zone | `zone_id`, `dwell_ms` |
| `queue_completed` | Person completes billing queue | `wait_seconds`, `queue_position_at_join` |
| `queue_abandoned` | Person leaves billing without purchase | `wait_seconds`, `abandoned` |
| `reentry` | Same person re-enters store | `visitor_id` |

### Edge Cases Handled

| Edge Case | How It's Handled |
|---|---|
| **Re-entry** | Tracked by `visitor_id`; `REENTRY` event emitted, deduplicated in funnel |
| **Staff filtering** | Persons present >50% of clip OR appearing in 3+ zones → `is_staff=true` |
| **Occlusion** | ByteTrack maintains tracks through 3-second gaps (90-frame buffer) |
| **Low confidence** | Events emitted with `confidence` score — not suppressed |
| **Group entry** | YOLOv8m resolves overlapping bounding boxes at 1080p |

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/test_funnel.py -v
```

### Test Results

```
47 passed, 0 failed, 81% coverage, 0 warnings
```

| Test File | Tests | Coverage Area |
|---|---|---|
| `test_ingestion.py` | 8 | Happy path, idempotency, validation, batch limits, edge cases |
| `test_metrics.py` | 6 | Staff exclusion, zero-purchase handling, visitor counting |
| `test_funnel.py` | 5 | Session dedup, re-entry, drop-off percentages |
| `test_anomalies.py` | 4 | Queue spike detection, severity levels, suggested actions |
| `test_health_heatmap.py` | 7 | Stale feed, DB status, normalisation, confidence flag |
| `test_pipeline.py` | 10 | UUID4 uniqueness, timestamps, schema validation, session sequences |

All test files include `# PROMPT:` blocks documenting the AI prompts used and `# CHANGES MADE:` sections explaining manual modifications.

---

## 📂 Project Structure

```
store-intelligence-api/
├── app/                        # FastAPI application
│   ├── main.py                 # Entrypoint — middleware, CORS, error handling
│   ├── models.py               # Pydantic v2 schemas (events, responses, enums)
│   ├── database.py             # SQLite + WAL — schema, connection, health
│   ├── ingestion.py            # POST /events/ingest — batch, idempotent
│   ├── metrics.py              # GET /stores/{id}/metrics — conversion, dwell
│   ├── funnel.py               # GET /stores/{id}/funnel — session-based
│   ├── heatmap.py              # GET /stores/{id}/heatmap — normalised zones
│   ├── anomalies.py            # GET /stores/{id}/anomalies — 3 types
│   ├── health.py               # GET /health — stale feed detection
│   └── dashboard.py            # SSE streaming + HTML serving
│
├── pipeline/                   # CCTV detection pipeline
│   ├── config.py               # Camera-zone mappings, thresholds
│   ├── detect.py               # YOLOv8m + ByteTrack main pipeline
│   ├── emit.py                 # Event emission (JSONL + API batching)
│   ├── load_pos.py             # POS CSV → SQLite loader
│   └── run.sh                  # One-command pipeline runner
│
├── dashboard/                  # Live web dashboard
│   ├── index.html              # Dark theme — KPIs, funnel, heatmap, feed
│   ├── index.css               # Glassmorphism, gradients, animations
│   └── index.js                # SSE connection + real-time rendering
│
├── tests/                      # Test suite (47 tests, 81% coverage)
│   ├── conftest.py             # Fixtures — isolated DBs, event factories
│   ├── test_ingestion.py       # Ingest endpoint tests
│   ├── test_metrics.py         # Metrics computation tests
│   ├── test_funnel.py          # Funnel dedup + drop-off tests
│   ├── test_anomalies.py       # Anomaly detection tests
│   ├── test_health_heatmap.py  # Health + heatmap tests
│   └── test_pipeline.py        # Pipeline schema compliance tests
│
├── docs/
│   ├── DESIGN.md               # Architecture + 3 AI-assisted decisions
│   └── CHOICES.md              # 5 technical decisions with options matrix
│
├── Dockerfile                  # Python 3.11-slim + health check
├── docker-compose.yml          # Single-command deploy with volume
├── requirements.txt            # Full dependencies (API + pipeline)
├── requirements-api.txt        # API-only dependencies (Docker image)
├── pytest.ini                  # Test configuration
└── README.md                   # This file
```

---

## 📖 Documentation

| Document | Contents |
|---|---|
| **[DESIGN.md](docs/DESIGN.md)** | System architecture diagram, component details, and 3 AI-assisted design decisions with reasoning on where AI was agreed with vs. overridden |
| **[CHOICES.md](docs/CHOICES.md)** | 3 technical decisions (model selection, event schema, storage) with options matrix, what AI suggested, what I chose, and why |

---

## ⚙️ Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `store_intelligence.db` | Path to SQLite database file |
| `DATA_DIR` | `./Dataset` | Path to dataset directory |
| `API_URL` | `http://localhost:8000` | API endpoint for pipeline event submission |

---

## 🔄 Scaling Considerations

The current architecture supports 2 stores (ST1008, ST2001). For 40+ stores in production:

| Component | Current | At Scale |
|---|---|---|
| Storage | SQLite (WAL) | PostgreSQL + TimescaleDB |
| Ingest buffer | Direct HTTP POST | Redis Streams / Kafka |
| Caching | None (compute on read) | Redis for hot metrics |
| Pipeline | Sequential per camera | GPU worker pool + async |
| Dashboard | Polling SSE | WebSocket + Redis pub/sub |
