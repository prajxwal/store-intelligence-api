# PROMPT: "Generate tests for health check and heatmap endpoints.
# Health: test healthy state, stale feed detection (>10 min lag), DB status.
# Heatmap: test normalisation 0-100, low data_confidence flag, zone representation."
#
# CHANGES MADE:
# - Combined health and heatmap tests into one file for coverage efficiency
# - Added test for DB health reporting
# - Added test for heatmap with known zone data verifying normalisation

"""Tests for GET /health and GET /stores/{id}/heatmap endpoints."""

import pytest
from tests.conftest import make_event


class TestHealth:
    """Test health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        """Health endpoint should always return 200."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "warning", "degraded"]
        assert "uptime_seconds" in data
        assert "database" in data

    @pytest.mark.asyncio
    async def test_health_shows_db_connected(self, client):
        """Health should report database as connected."""
        response = await client.get("/health")
        data = response.json()
        assert data["database"] == "connected"

    @pytest.mark.asyncio
    async def test_health_shows_stores(self, client):
        """After ingesting events, health should list the store."""
        events = [make_event(timestamp="2026-04-10T18:00:00Z")]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/health")
        data = response.json()
        assert len(data["stores"]) >= 1
        assert data["stores"][0]["store_id"] == "ST1008"
        assert data["stores"][0]["event_count"] >= 1

    @pytest.mark.asyncio
    async def test_stale_feed_warning(self, client):
        """Old events should trigger STALE_FEED warning."""
        events = [make_event(timestamp="2020-01-01T00:00:00Z")]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/health")
        data = response.json()
        stale_stores = [s for s in data["stores"] if s["status"] == "STALE_FEED"]
        assert len(stale_stores) >= 1


class TestHeatmap:
    """Test heatmap endpoint."""

    @pytest.mark.asyncio
    async def test_empty_heatmap(self, client):
        """Empty store should return low confidence and no zones."""
        response = await client.get("/stores/ST1008/heatmap?target_date=2026-04-10")
        assert response.status_code == 200
        data = response.json()
        assert data["data_confidence"] == "low"
        assert data["zones"] == []

    @pytest.mark.asyncio
    async def test_heatmap_normalisation(self, client):
        """Zone with most visits should have normalised_score = 100."""
        events = []
        # SKINCARE gets 5 visits
        for i in range(5):
            events.append(make_event("ZONE_ENTER", visitor_id=f"VIS_{i}",
                                     zone_id="SKINCARE",
                                     timestamp="2026-04-10T18:00:00Z"))
        # MAKEUP gets 2 visits
        for i in range(2):
            events.append(make_event("ZONE_ENTER", visitor_id=f"VIS_M{i}",
                                     zone_id="MAKEUP",
                                     timestamp="2026-04-10T18:00:00Z"))
        
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/heatmap?target_date=2026-04-10")
        data = response.json()
        
        zones = {z["zone_id"]: z for z in data["zones"]}
        assert zones["SKINCARE"]["normalised_score"] == 100.0
        assert zones["MAKEUP"]["normalised_score"] < 100.0

    @pytest.mark.asyncio
    async def test_low_confidence_flag(self, client):
        """Fewer than 20 sessions should flag data_confidence as low."""
        events = [
            make_event("ENTRY", visitor_id=f"VIS_{i}",
                       timestamp="2026-04-10T18:00:00Z")
            for i in range(5)
        ]
        await client.post("/events/ingest", json={"events": events})
        
        response = await client.get("/stores/ST1008/heatmap?target_date=2026-04-10")
        data = response.json()
        assert data["data_confidence"] == "low"
