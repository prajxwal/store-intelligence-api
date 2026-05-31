import httpx

r = httpx.get("http://localhost:8000/dashboard")
print("Dashboard:", r.status_code)

r2 = httpx.get("http://localhost:8000/dashboard/static/index.css")
print("CSS:", r2.status_code)

r3 = httpx.get("http://localhost:8000/dashboard/static/index.js")
print("JS:", r3.status_code)

r4 = httpx.get("http://localhost:8000/stores/ST1008/metrics")
m = r4.json()
print(f"Metrics: visitors={m['unique_visitors']}, events={m['total_events']}")
print("Fresh DB confirmed!" if m["total_events"] == 0 else "WARNING: stale data in DB!")
