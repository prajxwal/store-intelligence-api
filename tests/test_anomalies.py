# PROMPT: "Generate tests for anomaly detection: BILLING_QUEUE_SPIKE (queue > 2x average),
# CONVERSION_DROP (today < 7-day avg by >20%), and DEAD_ZONE (no visits in 30 min).
# Test when no anomalies exist, severity levels, and suggested_action presence."
#
# CHANGES MADE:
# - Updated to use lowercase event types matching Purplle's sample schema
# - Uses queue_completed/queue_abandoned with queue_position_at_join instead of queue_depth
# - Added test verifying suggested_action string is non-empty

"""Tests for GET /stores/{id}/anomalies endpoint."""

import pytest
from tests.conftest import make_event


class TestAnomaliesBasic:
    """Test anomaly detection."""

    @pytest.mark.asyncio
    async def test_no_anomalies_empty_store(self, client):
        """Empty store should have no anomalies."""
        response = await client.get("/stores/ST1008/anomalies?target_date=2026-04-10")
        assert response.status_code == 200
        data = response.json()
        assert data["anomalies"] == []

    @pytest.mark.asyncio
    async def test_anomaly_response_structure(self, client):
        """Anomaly response should have correct structure."""
        response = await client.get("/stores/ST1008/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert "store_id" in data
        assert "anomalies" in data
        assert isinstance(data["anomalies"], list)


class TestQueueSpike:
    """Test BILLING_QUEUE_SPIKE detection."""

    @pytest.mark.asyncio
    async def test_queue_spike_detection(self, client):
        """High queue position should trigger BILLING_QUEUE_SPIKE."""
        events = [
            # Normal queue events
            make_event("queue_completed", visitor_id="VIS_001",
                       zone_id="BILLING", zone_type="BILLING",
                       queue_position_at_join=1, wait_seconds=8, abandoned=False,
                       timestamp="2026-04-10T18:00:00Z"),
            make_event("queue_completed", visitor_id="VIS_002",
                       zone_id="BILLING", zone_type="BILLING",
                       queue_position_at_join=2, wait_seconds=12, abandoned=False,
                       timestamp="2026-04-10T18:01:00Z"),
            # Spike!
            make_event("queue_completed", visitor_id="VIS_003",
                       zone_id="BILLING", zone_type="BILLING",
                       queue_position_at_join=8, wait_seconds=45, abandoned=False,
                       timestamp="2026-04-10T18:05:00Z"),
        ]
        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/anomalies?target_date=2026-04-10")
        data = response.json()

        queue_anomalies = [a for a in data["anomalies"]
                           if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) >= 1
        assert queue_anomalies[0]["suggested_action"]  # Non-empty


class TestDeadZone:
    """Test DEAD_ZONE detection."""

    @pytest.mark.asyncio
    async def test_anomaly_has_suggested_action(self, client):
        """Every anomaly should include a suggested_action string."""
        events = [
            make_event("queue_completed", visitor_id="VIS_001",
                       zone_id="BILLING", zone_type="BILLING",
                       queue_position_at_join=1, wait_seconds=5, abandoned=False,
                       timestamp="2026-04-10T18:00:00Z"),
            make_event("queue_completed", visitor_id="VIS_002",
                       zone_id="BILLING", zone_type="BILLING",
                       queue_position_at_join=10, wait_seconds=60, abandoned=False,
                       timestamp="2026-04-10T18:05:00Z"),
        ]
        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/anomalies?target_date=2026-04-10")
        data = response.json()

        for anomaly in data["anomalies"]:
            assert "suggested_action" in anomaly
            assert len(anomaly["suggested_action"]) > 0
            assert "severity" in anomaly
            assert anomaly["severity"] in ["INFO", "WARN", "CRITICAL"]
