"""
Pipeline configuration — camera mappings, zone definitions, thresholds.
Derived from actual dataset analysis of Brigade_Bangalore store (ST1008).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "Dataset"))
VIDEO_DIR = os.path.join(DATA_DIR, "CCTV Footage")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# ─── Store Configuration ─────────────────────────────────────────────────────

STORE_ID = "ST1008"
STORE_NAME = "Brigade_Bangalore"
STORE_DATE = "2026-04-10"  # Date from video timestamps: 10/04/2026

# ─── Camera Mappings ──────────────────────────────────────────────────────────
# Based on visual analysis of the 5 camera feeds:
#   CAM 1: Skincare zone wall (Korean, Good Vibes, DermDoc, Minimalist, Aqualogica)
#   CAM 2: Makeup zone wall (Swiss Beauty, Lakme, Faces Canada, Maybelline) + Accessories
#   CAM 3: Store entrance/exit (glass door with Purplle signage) — ENTRY CAMERA
#   CAM 4: Back storage/stockroom — NOT customer-facing, skip
#   CAM 5: Cash counter + Accessories area — BILLING CAMERA

@dataclass
class CameraConfig:
    camera_id: str
    file_name: str
    zone_type: str  # "entry", "floor", "billing", "storage"
    zones: list[str] = field(default_factory=list)
    fps: float = 30.0
    is_customer_facing: bool = True
    # Entry line definition (for CAM 3): y-coordinate threshold 
    # Above this line = inside store, below = outside
    entry_line_y: Optional[int] = None


CAMERAS = {
    "CAM_01": CameraConfig(
        camera_id="CAM_01",
        file_name="CAM 1.mp4",
        zone_type="floor",
        zones=["SKINCARE", "KOREAN_BEAUTY", "CLEAN_BEAUTY"],
        fps=30.0,
    ),
    "CAM_02": CameraConfig(
        camera_id="CAM_02",
        file_name="CAM 2.mp4",
        zone_type="floor",
        zones=["MAKEUP", "ACCESSORIES", "FRAGRANCE"],
        fps=30.0,
    ),
    "CAM_03": CameraConfig(
        camera_id="CAM_03",
        file_name="CAM 3.mp4",
        zone_type="entry",
        zones=["ENTRY"],
        fps=30.0,
        entry_line_y=400,  # Approximate y-coordinate of the door threshold
    ),
    "CAM_04": CameraConfig(
        camera_id="CAM_04",
        file_name="CAM 4.mp4",
        zone_type="storage",
        zones=[],
        fps=25.0,
        is_customer_facing=False,
    ),
    "CAM_05": CameraConfig(
        camera_id="CAM_05",
        file_name="CAM 5.mp4",
        zone_type="billing",
        zones=["BILLING", "CASH_COUNTER", "ACCESSORIES"],
        fps=25.0,
    ),
}

# Customer-facing cameras only
ACTIVE_CAMERAS = {k: v for k, v in CAMERAS.items() if v.is_customer_facing}

# ─── Zone Definitions (from store layout image) ──────────────────────────────
# Top wall (left to right): EB Korean, The Face Shop, Good Vibes, DermDoc, 
#   Minimalist, Aqualogica, Lakme Skin, Accessories
# Bottom wall (left to right): Maybelline, Faces Canada, Lakme, Colorbar+Sugar,
#   Swiss Beauty, Renee/NY Bae, Alps Goodness, Streax
# Center: F.O.H (Front of House), Nail Unit, Fragrance, Makeup Unit
# Right side: Cash Counter, PMU (Permanent Makeup Unit)

ZONES = {
    "SKINCARE": {"display_name": "Skincare", "camera": "CAM_01"},
    "KOREAN_BEAUTY": {"display_name": "Korean Beauty", "camera": "CAM_01"},
    "CLEAN_BEAUTY": {"display_name": "Clean Beauty", "camera": "CAM_01"},
    "MAKEUP": {"display_name": "Makeup", "camera": "CAM_02"},
    "ACCESSORIES": {"display_name": "Accessories", "camera": "CAM_02"},
    "FRAGRANCE": {"display_name": "Fragrance", "camera": "CAM_02"},
    "FOH": {"display_name": "Front of House", "camera": "CAM_01"},
    "BILLING": {"display_name": "Cash Counter", "camera": "CAM_05"},
    "CASH_COUNTER": {"display_name": "Cash Counter", "camera": "CAM_05"},
    "ENTRY": {"display_name": "Entry/Exit", "camera": "CAM_03"},
}

# ─── Detection Thresholds ────────────────────────────────────────────────────

DETECTION_CONFIDENCE_THRESHOLD = 0.3  # Don't suppress low confidence — flag them
PERSON_CLASS_ID = 0  # COCO class ID for "person"

# Tracking
TRACK_BUFFER = 90       # Frames to keep lost tracks (3 seconds at 30fps)
MATCH_THRESHOLD = 0.7   # ByteTrack association threshold

# Dwell
DWELL_THRESHOLD_MS = 30000  # 30 seconds for ZONE_DWELL events
DWELL_EMIT_INTERVAL_MS = 30000  # Emit ZONE_DWELL every 30s of continued dwell

# Re-entry
REENTRY_SIMILARITY_THRESHOLD = 0.7  # Cosine similarity for re-ID matching
REENTRY_TIME_WINDOW_S = 300  # 5 minutes — max gap for re-entry detection

# Staff detection
STAFF_PRESENCE_THRESHOLD = 0.5  # Present in >50% of clip duration → likely staff
STAFF_ZONE_COUNT_THRESHOLD = 3  # Appears in 3+ zones → likely staff

# Frame processing
FRAME_SKIP = 2  # Process every Nth frame for speed (effectively 15fps from 30fps)

# Queue
QUEUE_ZONE_NAME = "BILLING"

# POS correlation
POS_CORRELATION_WINDOW_MIN = 5  # 5-minute window for POS correlation

# ─── Video Start Times ───────────────────────────────────────────────────────
# From video timestamp overlays: 10/04/2026 20:09-20:10
# All cameras start around 20:09-20:10 on 2026-04-10

VIDEO_START_TIMES = {
    "CAM_01": "2026-04-10T20:10:37",  # From timestamp overlay
    "CAM_02": "2026-04-10T20:10:12",
    "CAM_03": "2026-04-10T20:10:00",  # Approximate — entry cam timestamp not visible
    "CAM_04": "2026-04-10T20:09:57",
    "CAM_05": "2026-04-10T20:10:00",
}
