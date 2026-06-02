# Store Intelligence API

**End-to-end retail analytics from raw CCTV footage** -- transforms store camera feeds into real-time business metrics using YOLOv8 + ByteTrack person detection, structured event streaming, and a live analytics dashboard.

> **North Star Metric:** `Offline Store Conversion Rate = Visitors who completed a purchase / Total unique visitors`

---

## Quick Start

### Docker (One Command)

```bash
docker compose up --build
```

- API: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`
- Docs: `http://localhost:8000/docs`

### Local Development

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the API server
uvicorn app.main:app --reload --port 8000

# 3. Load POS transaction data
python -m pipeline.load_pos

# 4. Run detection pipeline (choose store)
python -m pipeline.detect --store store1   # Brigade Bangalore (ST1008)
python -m pipeline.detect --store store2   # Purplle Store 2 (ST2001)
```

---

## System Architecture

```
CCTV Clips --> YOLOv8m + ByteTrack --> Structured Events --> FastAPI --> Live Dashboard
(8 cameras)    (Person detection &      (JSONL + API POST)   (SQLite WAL)  (SSE real-time)
                tracking per frame)
```

| Layer | Technology | Purpose |
|---|---|---|
| **Detection** | YOLOv8m + ByteTrack | Person detection, multi-object tracking, zone classification |
| **Events** | 3-format JSONL (Entry/Exit, Zone, Queue) | Schema matching Purplle's sample format |
| **API** | FastAPI + aiosqlite (WAL mode) | 7 analytics endpoints, idempotent ingestion |
| **Dashboard** | Vanilla HTML/CSS/JS + SSE | Real-time KPIs, funnel, heatmap, anomalies |
| **Container** | Docker Compose | Single-command deployment with persistent volume |

### Multi-Store Support

The pipeline supports **2 stores** with distinct camera setups, zone layouts, and store IDs. The `--store` flag selects which store to process.

| | Store 1 (ST1008) | Store 2 (ST2001) |
|---|---|---|
| **Name** | Brigade Bangalore | Purplle Store 2 |
| **Date** | 10 April 2026 | 8 & 29 March 2026 |
| **Cameras** | 4 cams @ 1920x1080, 25-30fps | 4 cams @ 960x1080, 15fps |
| **Entry** | CAM 3 (glass door, side view) | entry 1 + entry 2 (top-down) |
| **Zones** | Skincare, Makeup, Korean Beauty, Fragrance | Skincare, Haircare, Wall Units |
| **Billing** | CAM 5 (cash counter) | billing_area (cash counter, top-down) |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/events/ingest` | Batch event ingestion (max 500, idempotent via event_id) |
| `GET` | `/stores/{id}/metrics` | Conversion rate, dwell times, gender split, top brands |
| `GET` | `/stores/{id}/funnel` | Entry -> Zone Visit -> Billing -> Purchase funnel |
| `GET` | `/stores/{id}/heatmap` | Zone activity heatmap (0-100 normalised) |
| `GET` | `/stores/{id}/anomalies` | Queue spikes, conversion drops, dead zones |
| `GET` | `/health` | Service health + per-store STALE_FEED detection |
| `GET` | `/dashboard` | Live web dashboard (SSE-powered) |

### Example Usage

```bash
# Health check
curl http://localhost:8000/health

# Store metrics (with date filter)
curl http://localhost:8000/stores/ST1008/metrics?target_date=2026-04-10

# Conversion funnel
curl http://localhost:8000/stores/ST1008/funnel?target_date=2026-04-10

# Zone heatmap
curl http://localhost:8000/stores/ST1008/heatmap?target_date=2026-04-10

# Anomaly detection
curl http://localhost:8000/stores/ST1008/anomalies?target_date=2026-04-10
```

---

## Detection Pipeline

### Camera Setup

**Store 1 -- Brigade Bangalore (ST1008)**

| Camera | File | Resolution | View | Zones |
|---|---|---|---|---|
| CAM 1 | `CAM 1 - zone.mp4` | 1920x1080 @ 30fps | Skincare wall (Korean, Face Shop, DermaCo) | `SKINCARE`, `KOREAN_BEAUTY`, `CLEAN_BEAUTY` |
| CAM 2 | `CAM 2 - zone.mp4` | 1920x1080 @ 30fps | Makeup wall (Lakme, Faces Canada, Maybelline) | `MAKEUP`, `ACCESSORIES`, `FRAGRANCE` |
| CAM 3 | `CAM 3 - entry.mp4` | 1920x1080 @ 30fps | Store entrance (glass door with Purplle branding) | `ENTRY` / `EXIT` detection |
| CAM 5 | `CAM 5 - billing.mp4` | 1920x1080 @ 25fps | Cash counter + accessories area | `BILLING`, `CASH_COUNTER` |

**Store 2 -- Purplle Store 2 (ST2001)**

| Camera | File | Resolution | View | Zones |
|---|---|---|---|---|
| Entry 1 | `entry 1.mp4` | 960x1080 @ 15fps | Glass door entrance (top-down, 29/03/2026) | `ENTRY` / `EXIT` detection |
| Entry 2 | `entry 2.mp4` | 960x1080 @ 15fps | Same entrance (different date, 08/03/2026) | `ENTRY` / `EXIT` detection |
| Zone | `zone.mp4` | 960x1080 @ 15fps | Narrow aisle -- Pilgrim, skincare, haircare wall units | `SKINCARE`, `HAIRCARE` |
| Billing | `billing_area.mp4` | 960x1080 @ 15fps | Cash counter from above + makeup displays | `BILLING`, `CASH_COUNTER`, `MAKEUP` |

### Processing Flow

```
Frame -> YOLOv8m (person detection, COCO class 0)
      -> ByteTrack (persistent ID across frames, 90-frame buffer)
      -> Zone Classification (spatial heuristics from store layout analysis)
      -> Entry/Exit Detection (vertical movement across door threshold)
      -> Staff Classification (present >50% of clip OR seen in 3+ zones)
      -> Event Emission (UUID4 event IDs, ISO-8601 timestamps, JSONL + HTTP POST)
```

### Event Schema (3 Formats)

Events are emitted in Purplle's expected 3-schema format:

**1. Entry/Exit Events**

| Field | Example |
|---|---|
| `event_type` | `entry`, `exit` |
| `id_token` | `ID_60001` |
| `store_code` | `store_1008` |
| `camera_id` | `cam_03` |
| `event_timestamp` | `2026-04-10T20:10:37.000000` |
| `is_staff` | `false` |

**2. Zone Events**

| Field | Example |
|---|---|
| `event_type` | `zone_entered`, `zone_exited`, `zone_dwell` |
| `zone_id` | `PURPLLE_BLR_1008_Z01` |
| `zone_name` | `Skincare Wall` |
| `zone_type` | `SHELF`, `DISPLAY`, `BILLING` |
| `is_revenue_zone` | `Yes` |
| `zone_hotspot_x/y` | Normalised coordinates |

**3. Queue Events**

| Field | Example |
|---|---|
| `event_type` | `queue_completed`, `queue_abandoned` |
| `queue_join_ts` / `queue_exit_ts` | ISO-8601 timestamps |
| `wait_seconds` | `45` |
| `queue_position_at_join` | `3` |
| `abandoned` | `false` |

### Edge Cases

| Edge Case | Approach |
|---|---|
| **Re-entry** | Tracked by `visitor_id`; `reentry` event emitted, deduplicated in funnel |
| **Staff filtering** | Persons present >50% of clip OR appearing in 3+ zones -> `is_staff=true` |
| **Occlusion** | ByteTrack maintains tracks through 3-second gaps (90-frame buffer) |
| **Low confidence** | Events emitted with `confidence` score -- not suppressed, flagged in heatmap |
| **Group entry** | YOLOv8m resolves overlapping bounding boxes at 1080p |
| **Numpy types** | Custom JSON encoder handles `float32` from YOLO output |

---

## Testing

```bash
# Run all tests with coverage
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/test_funnel.py -v
```

### Results

```
47 passed, 0 failed, 81% coverage
```

| Test File | Tests | Coverage |
|---|---|---|
| `test_ingestion.py` | 13 | Batch ingestion, idempotency, validation, edge cases |
| `test_pipeline.py` | 12 | UUID4 uniqueness, ISO-8601 timestamps, schema compliance |
| `test_health_heatmap.py` | 7 | Stale feed detection, zone normalisation, confidence flags |
| `test_metrics.py` | 6 | Staff exclusion, zero-purchase handling, visitor counting |
| `test_funnel.py` | 5 | Session dedup, re-entry, drop-off percentage calculation |
| `test_anomalies.py` | 4 | Queue spike detection, severity levels, suggested actions |

---

## Project Structure

```
store-intelligence-api/
|-- app/                          # FastAPI application
|   |-- main.py                   # Entrypoint -- middleware, CORS, error handling
|   |-- models.py                 # Pydantic v2 schemas (8 event types, responses)
|   |-- database.py               # SQLite + WAL -- schema, connection, health
|   |-- ingestion.py              # POST /events/ingest -- batch, idempotent
|   |-- metrics.py                # GET /stores/{id}/metrics -- conversion, dwell, brands
|   |-- funnel.py                 # GET /stores/{id}/funnel -- session-based
|   |-- heatmap.py                # GET /stores/{id}/heatmap -- normalised zones
|   |-- anomalies.py              # GET /stores/{id}/anomalies -- 3 anomaly types
|   |-- health.py                 # GET /health -- stale feed detection
|   +-- dashboard.py              # SSE streaming + HTML serving
|
|-- pipeline/                     # CCTV detection pipeline
|   |-- config.py                 # Multi-store camera configs, zone metadata, thresholds
|   |-- detect.py                 # YOLOv8m + ByteTrack -- --store flag for multi-store
|   |-- emit.py                   # Event emission (3 formats, JSONL + API batching)
|   |-- load_pos.py               # POS CSV -> SQLite loader
|   +-- extract_frames.py         # Frame extraction utility for visual analysis
|
|-- dashboard/                    # Live web dashboard
|   |-- index.html                # Monochrome dark theme, Roboto Mono, store selector
|   |-- index.css                 # Black/white palette, straight lines, no curves
|   +-- index.js                  # SSE connection + real-time rendering
|
|-- tests/                        # 47 tests, 81% coverage
|   |-- conftest.py               # Fixtures -- isolated DBs, event factories
|   |-- test_ingestion.py         # Ingest endpoint tests
|   |-- test_metrics.py           # Metrics computation tests
|   |-- test_funnel.py            # Funnel dedup + drop-off tests
|   |-- test_anomalies.py         # Anomaly detection tests
|   |-- test_health_heatmap.py    # Health + heatmap tests
|   +-- test_pipeline.py          # Pipeline schema compliance tests
|
|-- docs/
|   |-- DESIGN.md                 # System architecture + AI-assisted design decisions
|   +-- CHOICES.md                # 5 technical decisions with options matrix
|
|-- Dockerfile                    # Python 3.11-slim + health check
|-- docker-compose.yml            # Single-command deploy with persistent volume
|-- requirements.txt              # Full dependencies (API + pipeline)
|-- requirements-api.txt          # API-only dependencies (Docker image)
|-- pytest.ini                    # Test configuration + coverage
+-- README.md
```

---

## Documentation

| Document | Contents |
|---|---|
| **[DESIGN.md](docs/DESIGN.md)** | System architecture, component details, AI-assisted design decisions (model selection, storage engine, event schema) |
| **[CHOICES.md](docs/CHOICES.md)** | 5 technical decisions: YOLOv8m selection, event schema design, SQLite WAL, demographics approach, schema alignment with Purplle's sample format |

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `store_intelligence.db` | Path to SQLite database file |
| `DATA_DIR` | `./Dataset` | Path to dataset directory (Store 1, Store 2 subdirs) |
| `API_URL` | `http://localhost:8000` | API endpoint for pipeline event submission |

---

## Scaling Considerations

The current architecture supports 2 stores (ST1008, ST2001). For 40+ stores in production:

| Component | Current | At Scale |
|---|---|---|
| Storage | SQLite (WAL) | PostgreSQL + TimescaleDB |
| Ingest buffer | Direct HTTP POST | Redis Streams / Kafka |
| Caching | None (compute on read) | Redis for hot metrics |
| Pipeline | Sequential per camera | GPU worker pool + async |
| Dashboard | Polling SSE | WebSocket + Redis pub/sub |
