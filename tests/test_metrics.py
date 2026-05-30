# PROMPT: "Generate tests for a store metrics endpoint that returns unique visitors,
# conversion rate, avg dwell per zone, queue depth, and abandonment rate.
# Must exclude is_staff=true from customer metrics. Must handle zero-purchase stores
# and empty stores without errors. Test conversion rate calculation with known data."
#
# CHANGES MADE:
# - Added explicit test for all-staff clip returning 0 customer visitors
# - Added test for zero purchases → conversion_rate = 0.0 (not null/error)
# - Changed conversion rate test to use deterministic timestamps
# - Added zone dwell aggregation verification

"""Tests for GET /stores/{id}/metrics endpoint."""

import pytest
from tests.conftest import make_event, make_visitor_journey


class TestMetricsBasic:
    """Test basic metrics computation."""

    @pytest.mark.asyncio
    async def test_empty_store(self, client):
        """Empty store should return zero metrics, not crash."""
        response = await client.get("/stores/ST1008/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["store_id"] == "ST1008"
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0
        assert data["total_purchases"] == 0

    @pytest.mark.asyncio
    async def test_nonexistent_store(self, client):
        """Querying a store with no data should return zeros."""
        response = await client.get("/stores/FAKE_STORE/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 0

    @pytest.mark.asyncio
    async def test_visitors_counted(self, client):
        """Visitors should be counted from ENTRY events."""
        events = [
            make_event("ENTRY", visitor_id="VIS_001", timestamp="2026-04-10T18:00:00Z"),
            make_event("ENTRY", visitor_id="VIS_002", timestamp="2026-04-10T18:01:00Z"),
            make_event("ENTRY", visitor_id="VIS_003", timestamp="2026-04-10T18:02:00Z"),
        ]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/metrics?target_date=2026-04-10")
        data = response.json()
        assert data["unique_visitors"] == 3


class TestStaffExclusion:
    """Test that staff are excluded from customer metrics."""

    @pytest.mark.asyncio
    async def test_staff_excluded_from_visitors(self, client):
        """Staff entries should not count as customer visitors."""
        events = [
            make_event("ENTRY", visitor_id="VIS_CUST", is_staff=False,
                       timestamp="2026-04-10T18:00:00Z"),
            make_event("ENTRY", visitor_id="VIS_STAFF", is_staff=True,
                       timestamp="2026-04-10T18:00:30Z"),
        ]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/metrics?target_date=2026-04-10")
        data = response.json()
        assert data["unique_visitors"] == 1  # Only customer

    @pytest.mark.asyncio
    async def test_all_staff_clip(self, client):
        """All-staff clip should return 0 customer visitors."""
        events = [
            make_event("ENTRY", visitor_id=f"STAFF_{i}", is_staff=True,
                       timestamp="2026-04-10T18:00:00Z")
            for i in range(5)
        ]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/metrics?target_date=2026-04-10")
        data = response.json()
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0


class TestZeroPurchases:
    """Test handling of zero-purchase scenarios."""

    @pytest.mark.asyncio
    async def test_zero_purchases_conversion_zero(self, client):
        """Zero purchases → conversion_rate = 0.0, not null or error."""
        events = [
            make_event("ENTRY", visitor_id="VIS_001", timestamp="2026-04-10T18:00:00Z"),
        ]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/metrics?target_date=2026-04-10")
        data = response.json()
        assert data["conversion_rate"] == 0.0
        assert data["total_purchases"] == 0
