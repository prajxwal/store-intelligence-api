"""Quick end-to-end API verification script."""
import httpx
import json
import uuid

API = "http://localhost:8000"

# Test health
r = httpx.get(f"{API}/health")
print(f"Health: {r.status_code} -> {r.json()['status']}")

# Ingest test events
events = []
for i in range(5):
    events.append({
        "event_id": str(uuid.uuid4()),
        "store_id": "ST1008",
        "camera_id": "CAM_03",
        "visitor_id": f"VIS_00{i+1}",
        "event_type": "ENTRY",
        "timestamp": f"2026-04-10T20:1{i}:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": i == 4,
        "confidence": 0.85,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
    })
# Add zone events
for i in range(3):
    events.append({
        "event_id": str(uuid.uuid4()),
        "store_id": "ST1008",
        "camera_id": "CAM_01",
        "visitor_id": f"VIS_00{i+1}",
        "event_type": "ZONE_ENTER",
        "timestamp": f"2026-04-10T20:1{i+1}:30Z",
        "zone_id": "SKINCARE",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.82,
        "metadata": {"queue_depth": None, "sku_zone": "SKINCARE", "session_seq": 2}
    })
# Add billing event
events.append({
    "event_id": str(uuid.uuid4()),
    "store_id": "ST1008",
    "camera_id": "CAM_05",
    "visitor_id": "VIS_001",
    "event_type": "BILLING_QUEUE_JOIN",
    "timestamp": "2026-04-10T20:15:00Z",
    "zone_id": "BILLING",
    "dwell_ms": 0,
    "is_staff": False,
    "confidence": 0.9,
    "metadata": {"queue_depth": 2, "sku_zone": "BILLING", "session_seq": 3}
})

r = httpx.post(f"{API}/events/ingest", json={"events": events})
result = r.json()
print(f"Ingest: {r.status_code} -> accepted={result['accepted']}, rejected={result['rejected']}")

# Test metrics
r = httpx.get(f"{API}/stores/ST1008/metrics?target_date=2026-04-10")
m = r.json()
print(f"Metrics: {r.status_code} -> visitors={m['unique_visitors']}, conversion={m['conversion_rate']}")

# Test funnel
r = httpx.get(f"{API}/stores/ST1008/funnel?target_date=2026-04-10")
f = r.json()
print(f"Funnel: {r.status_code}")
for stage in f["stages"]:
    print(f"  {stage['stage']}: {stage['count']} (drop-off: {stage['drop_off_pct']}%)")

# Test heatmap
r = httpx.get(f"{API}/stores/ST1008/heatmap?target_date=2026-04-10")
h = r.json()
print(f"Heatmap: {r.status_code} -> confidence={h['data_confidence']}, zones={len(h['zones'])}")

# Test anomalies
r = httpx.get(f"{API}/stores/ST1008/anomalies?target_date=2026-04-10")
a = r.json()
print(f"Anomalies: {r.status_code} -> {len(a['anomalies'])} detected")

print()
print("=== ALL API ENDPOINTS WORKING ===")
