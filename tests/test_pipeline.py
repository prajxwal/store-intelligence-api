# PROMPT: "Generate tests for a CCTV detection pipeline that processes video clips
# and emits structured events. Test schema compliance of emitted events, event_id
# uniqueness, timestamp ordering, staff flag presence, and event type coverage."
#
# CHANGES MADE:
# - Updated to lowercase event types matching Purplle's sample schema
# - Tests new entry/exit, zone, and queue event creators
# - Added test for visitor ID format (ID_60001)

"""Tests for the detection pipeline event emission and schema compliance."""

import uuid
from datetime import datetime

import pytest

from pipeline.emit import EventEmitter
from app.models import EventIngest, EventType


class TestEventSchema:
    """Test that emitted events conform to the Purplle schema."""

    def test_create_event_has_required_fields(self):
        """Every event must have all required fields."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_event(
            camera_id="CAM_03",
            visitor_id="VIS_0001",
            event_type="entry",
            timestamp=datetime(2026, 4, 10, 18, 0, 0),
            confidence=0.85,
        )

        required_fields = [
            "event_id", "store_id", "camera_id", "visitor_id",
            "event_type", "timestamp", "zone_id", "dwell_ms",
            "is_staff", "confidence", "metadata",
        ]
        for field in required_fields:
            assert field in event, f"Missing required field: {field}"

    def test_event_id_is_valid_uuid4(self):
        """event_id must be a valid UUID v4."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_event(
            camera_id="CAM_03",
            visitor_id="VIS_0001",
            event_type="entry",
            timestamp=datetime(2026, 4, 10, 18, 0, 0),
            confidence=0.85,
        )
        # Should not raise
        parsed = uuid.UUID(event["event_id"], version=4)
        assert parsed.version == 4

    def test_event_ids_are_unique(self):
        """Each event must have a globally unique event_id."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        ids = set()
        base_time = datetime(2026, 4, 10, 18, 0, 0)
        for i in range(100):
            from datetime import timedelta
            event = emitter.create_event(
                camera_id="CAM_03",
                visitor_id=f"VIS_{i:04d}",
                event_type="entry",
                timestamp=base_time + timedelta(seconds=i),
                confidence=0.85,
            )
            assert event["event_id"] not in ids, f"Duplicate event_id at iteration {i}"
            ids.add(event["event_id"])

    def test_timestamp_format_iso8601(self):
        """Timestamps must be ISO-8601 UTC."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_event(
            camera_id="CAM_03",
            visitor_id="VIS_0001",
            event_type="entry",
            timestamp=datetime(2026, 4, 10, 18, 30, 45),
            confidence=0.85,
        )
        ts = event["timestamp"]
        assert ts.endswith("Z"), f"Timestamp should end with Z: {ts}"
        # Should parse without error
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

    def test_event_validates_against_pydantic(self):
        """Emitted events must pass Pydantic validation."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_event(
            camera_id="CAM_03",
            visitor_id="VIS_0001",
            event_type="entry",
            timestamp=datetime(2026, 4, 10, 18, 0, 0),
            confidence=0.85,
        )
        # Should not raise
        validated = EventIngest(**event)
        assert validated.event_type == EventType.entry

    def test_zone_dwell_event_has_dwell_ms(self):
        """zone_dwell events must include dwell_ms > 0."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_event(
            camera_id="CAM_01",
            visitor_id="VIS_0001",
            event_type="zone_dwell",
            timestamp=datetime(2026, 4, 10, 18, 1, 0),
            zone_id="SKINCARE",
            dwell_ms=45000,
            confidence=0.9,
        )
        assert event["dwell_ms"] == 45000
        assert event["zone_id"] == "SKINCARE"


class TestSessionSequence:
    """Test session sequence tracking."""

    def test_session_seq_increments(self):
        """session_seq should increment per visitor."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        vid = "VIS_0001"

        e1 = emitter.create_event("CAM_03", vid, "entry", datetime.now(), confidence=0.9)
        e2 = emitter.create_event("CAM_01", vid, "zone_entered", datetime.now(),
                                  zone_id="SKINCARE", confidence=0.85)
        e3 = emitter.create_event("CAM_03", vid, "exit", datetime.now(), confidence=0.88)

        assert e1["metadata"]["session_seq"] == 1
        assert e2["metadata"]["session_seq"] == 2
        assert e3["metadata"]["session_seq"] == 3

    def test_different_visitors_independent_sequences(self):
        """Different visitors should have independent session sequences."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")

        e1 = emitter.create_event("CAM_03", "VIS_A", "entry", datetime.now(), confidence=0.9)
        e2 = emitter.create_event("CAM_03", "VIS_B", "entry", datetime.now(), confidence=0.9)
        e3 = emitter.create_event("CAM_01", "VIS_A", "zone_entered", datetime.now(),
                                  zone_id="SKINCARE", confidence=0.85)

        assert e1["metadata"]["session_seq"] == 1
        assert e2["metadata"]["session_seq"] == 1  # VIS_B starts at 1
        assert e3["metadata"]["session_seq"] == 2  # VIS_A continues at 2


class TestEventTypes:
    """Test that all required event types can be created."""

    def test_all_event_types_valid(self):
        """All event types should create valid events."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event_types = [
            "entry", "exit", "zone_entered", "zone_exited",
            "zone_dwell", "queue_completed",
            "queue_abandoned", "reentry",
        ]
        for et in event_types:
            event = emitter.create_event(
                camera_id="CAM_03",
                visitor_id="VIS_TEST",
                event_type=et,
                timestamp=datetime.now(),
                confidence=0.8,
                zone_id="SKINCARE" if "zone" in et or "queue" in et else None,
            )
            validated = EventIngest(**event)
            assert validated.event_type.value == et

    def test_queue_completed_event(self):
        """queue_completed event should include queue timing fields."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        join_ts = datetime(2026, 4, 10, 18, 13, 5)
        exit_ts = datetime(2026, 4, 10, 18, 15, 31)
        event = emitter.create_queue_event(
            camera_id="CAM_05",
            track_id=102,
            event_type="queue_completed",
            zone="BILLING",
            queue_join_ts=join_ts,
            queue_exit_ts=exit_ts,
            queue_served_ts=datetime(2026, 4, 10, 18, 13, 13),
            wait_seconds=8,
            queue_position_at_join=2,
            abandoned=False,
        )
        assert event["event_type"] == "queue_completed"
        assert event["wait_seconds"] == 8
        assert event["abandoned"] is False
        assert event["queue_position_at_join"] == 2


class TestEntryExitEvents:
    """Test the Purplle-format entry/exit event creator."""

    def test_entry_event_format(self):
        """Entry events should use id_token and store_code format."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        vid = emitter.next_visitor_id()
        event = emitter.create_entry_exit_event(
            camera_id="CAM_03",
            visitor_id=vid,
            event_type="entry",
            timestamp=datetime(2026, 4, 10, 18, 10, 5),
        )
        assert event["event_type"] == "entry"
        assert event["id_token"] == vid
        assert "store_code" in event
        assert vid.startswith("ID_")

    def test_zone_event_has_metadata(self):
        """Zone events should include zone_name, zone_type, is_revenue_zone."""
        emitter = EventEmitter(store_id="ST1008", output_dir="./test_output")
        event = emitter.create_zone_event(
            camera_id="CAM_01",
            track_id=101,
            event_type="zone_entered",
            timestamp=datetime(2026, 4, 10, 18, 10, 45),
            zone="SKINCARE",
            hotspot_x=412.6,
            hotspot_y=238.4,
        )
        assert event["zone_name"] is not None
        assert event["zone_type"] == "SHELF"
        assert event["is_revenue_zone"] == "Yes"
        assert event["zone_hotspot_x"] == 412.6
