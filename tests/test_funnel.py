# PROMPT: "Generate tests for a conversion funnel endpoint with stages:
# Entry → Zone Visit → Billing Queue → Purchase. The funnel uses sessions
# (unique visitor_id), not raw events. Re-entries must not double-count."
#
# CHANGES MADE:
# - Updated to lowercase event types matching Purplle's sample schema
# - zone_entered/zone_exited instead of ZONE_ENTER/ZONE_EXIT
# - Added zone_type for billing zone queries

"""Tests for GET /stores/{id}/funnel endpoint."""

import pytest
from tests.conftest import make_event, make_visitor_journey


class TestFunnelBasic:
    """Test funnel computation."""

    @pytest.mark.asyncio
    async def test_empty_funnel(self, client):
        """Empty store should return zero funnel stages."""
        response = await client.get("/stores/ST1008/funnel?target_date=2026-04-10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["stages"]) == 4
        assert all(s["count"] == 0 for s in data["stages"])

    @pytest.mark.asyncio
    async def test_full_journey_funnel(self, client):
        """A complete visitor journey should show 1 at each stage."""
        events = make_visitor_journey(
            visitor_id="VIS_FULL",
            timestamp_base="2026-04-10T18:00:00Z",
        )
        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/funnel?target_date=2026-04-10")
        data = response.json()
        stages = {s["stage"]: s["count"] for s in data["stages"]}

        assert stages["Entry"] >= 1
        assert stages["Zone Visit"] >= 1
        assert stages["Billing Queue"] >= 1

    @pytest.mark.asyncio
    async def test_entry_only_visitor(self, client):
        """Visitor who enters and exits without zone visit → drop at Zone Visit."""
        events = [
            make_event("entry", visitor_id="VIS_BOUNCE",
                       timestamp="2026-04-10T18:00:00Z"),
            make_event("exit", visitor_id="VIS_BOUNCE",
                       timestamp="2026-04-10T18:00:30Z"),
        ]
        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/funnel?target_date=2026-04-10")
        data = response.json()
        stages = {s["stage"]: s["count"] for s in data["stages"]}

        assert stages["Entry"] == 1
        assert stages["Zone Visit"] == 0


class TestFunnelReentry:
    """Test that re-entries don't double-count."""

    @pytest.mark.asyncio
    async def test_reentry_not_double_counted(self, client):
        """Same visitor re-entering should not appear as 2 entries in funnel."""
        visitor_id = "VIS_REENTRY"
        events = [
            make_event("entry", visitor_id=visitor_id,
                       timestamp="2026-04-10T18:00:00Z"),
            make_event("exit", visitor_id=visitor_id,
                       timestamp="2026-04-10T18:10:00Z"),
            make_event("reentry", visitor_id=visitor_id,
                       timestamp="2026-04-10T18:15:00Z"),
        ]
        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/funnel?target_date=2026-04-10")
        data = response.json()
        stages = {s["stage"]: s["count"] for s in data["stages"]}

        # Should count as 1 unique visitor, not 2
        assert stages["Entry"] == 1


class TestFunnelDropOff:
    """Test drop-off percentage calculations."""

    @pytest.mark.asyncio
    async def test_drop_off_percentages(self, client):
        """With known data, verify drop-off % between stages."""
        # 3 visitors enter, 2 visit zones, 1 reaches billing
        events = []
        for vid in ["VIS_A", "VIS_B", "VIS_C"]:
            events.append(make_event("entry", visitor_id=vid,
                                     timestamp="2026-04-10T18:00:00Z"))

        # Only A and B visit zones
        for vid in ["VIS_A", "VIS_B"]:
            events.append(make_event("zone_entered", visitor_id=vid,
                                     zone_id="SKINCARE", zone_type="SHELF",
                                     zone_name="Skincare Wall",
                                     timestamp="2026-04-10T18:01:00Z"))

        # Only A reaches billing
        events.append(make_event("zone_entered", visitor_id="VIS_A",
                                 zone_id="BILLING", zone_type="BILLING",
                                 zone_name="Billing Counter",
                                 timestamp="2026-04-10T18:02:00Z"))

        await client.post("/events/ingest", json={"events": events})

        response = await client.get("/stores/ST1008/funnel?target_date=2026-04-10")
        data = response.json()
        stages = {s["stage"]: s for s in data["stages"]}

        assert stages["Entry"]["count"] == 3
        assert stages["Zone Visit"]["count"] == 2
        assert stages["Billing Queue"]["count"] == 1

        # Drop-off: Entry→Zone = 33.3%, Zone→Billing = 50%
        assert stages["Zone Visit"]["drop_off_pct"] == pytest.approx(33.3, abs=0.5)
        assert stages["Billing Queue"]["drop_off_pct"] == pytest.approx(50.0, abs=0.5)
