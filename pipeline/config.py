"""
Pipeline configuration — multi-store camera mappings, zone definitions, thresholds.
Supports Store 1 (Brigade Bangalore) and Store 2 (Purplle Store 2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "Dataset"))
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# ─── Camera Config ───────────────────────────────────────────────────────────

@dataclass
class CameraConfig:
    camera_id: str
    file_name: str
    zone_type: str  # "entry", "floor", "billing", "storage"
    zones: list[str] = field(default_factory=list)
    fps: float = 30.0
    is_customer_facing: bool = True
    entry_line_y: Optional[int] = None


# ─── Store Configs ───────────────────────────────────────────────────────────

@dataclass
class StoreConfig:
    store_id: str
    store_name: str
    store_date: str
    video_dir: str
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    video_start_times: dict[str, str] = field(default_factory=dict)

    @property
    def active_cameras(self) -> dict[str, CameraConfig]:
        return {k: v for k, v in self.cameras.items() if v.is_customer_facing}

    @property
    def store_code(self) -> str:
        return f"store_{self.store_id.replace('ST', '')}"


# ── Store 1: Brigade Bangalore (ST1008) ──────────────────────────────────────
# CAM 1: Skincare wall — FarmStay/Korean, The Face Shop, Good Vibes, DermaCo, Minimalist, Aqualogica
# CAM 2: Makeup wall — Swiss Beauty, Lakme, Faces Canada, Maybelline + Accessories
# CAM 3: Store entrance/exit — glass door with Purplle signage (ENTRY CAMERA)
# CAM 5: Cash counter + Accessories area (BILLING CAMERA)
# Note: CAM 4 (storage) removed in updated dataset

STORE1 = StoreConfig(
    store_id="ST1008",
    store_name="Brigade_Bangalore",
    store_date="2026-04-10",
    video_dir=os.path.join(DATA_DIR, "Store 1"),
    cameras={
        "CAM_01": CameraConfig(
            camera_id="CAM_01",
            file_name="CAM 1 - zone.mp4",
            zone_type="floor",
            zones=["SKINCARE", "KOREAN_BEAUTY", "CLEAN_BEAUTY"],
            fps=30.0,
        ),
        "CAM_02": CameraConfig(
            camera_id="CAM_02",
            file_name="CAM 2 - zone.mp4",
            zone_type="floor",
            zones=["MAKEUP", "ACCESSORIES", "FRAGRANCE"],
            fps=30.0,
        ),
        "CAM_03": CameraConfig(
            camera_id="CAM_03",
            file_name="CAM 3 - entry.mp4",
            zone_type="entry",
            zones=["ENTRY"],
            fps=30.0,
            entry_line_y=400,
        ),
        "CAM_05": CameraConfig(
            camera_id="CAM_05",
            file_name="CAM 5 - billing.mp4",
            zone_type="billing",
            zones=["BILLING", "CASH_COUNTER", "ACCESSORIES"],
            fps=25.0,
        ),
    },
    video_start_times={
        "CAM_01": "2026-04-10T20:10:37",
        "CAM_02": "2026-04-10T20:10:12",
        "CAM_03": "2026-04-10T20:10:00",
        "CAM_05": "2026-04-10T20:10:00",
    },
)


# ── Store 2 (ST2001) ─────────────────────────────────────────────────────────
# From frame analysis:
#   entry 1.mp4 (CAM1): Glass door entrance, looking down — 960x1080. Date: 29/03/2026
#   entry 2.mp4 (CAM1): Same entrance, different date — 960x1080. Date: 08/03/2026
#   zone.mp4 (CAM2): Narrow aisle between wall units (Pilgrim, skincare, haircare) — 960x1080
#   billing_area.mp4 (CAM6): Cash counter from above + makeup displays — 960x1080
# Layout: Wall Units 1-19 around perimeter, MK Gondola in center, F.O.H, Cash Counter top-center

STORE2 = StoreConfig(
    store_id="ST2001",
    store_name="Purplle_Store2",
    store_date="2026-03-29",
    video_dir=os.path.join(DATA_DIR, "Store 2"),
    cameras={
        "S2_ENTRY1": CameraConfig(
            camera_id="S2_ENTRY1",
            file_name="entry 1.mp4",
            zone_type="entry",
            zones=["ENTRY"],
            fps=15.0,
            entry_line_y=300,  # Door threshold — top of frame is outside, bottom is inside
        ),
        "S2_ENTRY2": CameraConfig(
            camera_id="S2_ENTRY2",
            file_name="entry 2.mp4",
            zone_type="entry",
            zones=["ENTRY"],
            fps=15.0,
            entry_line_y=300,
        ),
        "S2_ZONE": CameraConfig(
            camera_id="S2_ZONE",
            file_name="zone.mp4",
            zone_type="floor",
            zones=["SKINCARE", "HAIRCARE", "WALL_UNIT"],
            fps=15.0,
        ),
        "S2_BILLING": CameraConfig(
            camera_id="S2_BILLING",
            file_name="billing_area.mp4",
            zone_type="billing",
            zones=["BILLING", "CASH_COUNTER", "MAKEUP"],
            fps=15.0,
        ),
    },
    video_start_times={
        "S2_ENTRY1": "2026-03-29T19:39:00",
        "S2_ENTRY2": "2026-03-08T13:40:00",
        "S2_ZONE":   "2026-03-08T15:28:00",
        "S2_BILLING": "2026-03-08T18:28:00",
    },
)

# ─── Store Registry ──────────────────────────────────────────────────────────

STORES: dict[str, StoreConfig] = {
    "store1": STORE1,
    "store2": STORE2,
}

# ─── Default active store (backward-compatible) ─────────────────────────────

STORE_ID = STORE1.store_id
STORE_NAME = STORE1.store_name
STORE_DATE = STORE1.store_date
VIDEO_DIR = STORE1.video_dir
STORE_CODE = STORE1.store_code

CAMERAS = STORE1.cameras
ACTIVE_CAMERAS = STORE1.active_cameras

VIDEO_START_TIMES = STORE1.video_start_times


# ─── Zone Definitions ────────────────────────────────────────────────────────

ZONES = {
    # Store 1 zones
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
    # Store 2 zones
    "HAIRCARE": {"display_name": "Haircare", "camera": "S2_ZONE"},
    "WALL_UNIT": {"display_name": "Wall Unit", "camera": "S2_ZONE"},
}

# Zone metadata — maps zone_id to zone_name, zone_type, is_revenue_zone
ZONE_METADATA = {
    # Store 1 zones
    "SKINCARE":      {"zone_name": "Skincare Wall",      "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
    "KOREAN_BEAUTY": {"zone_name": "Korean Beauty",      "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
    "CLEAN_BEAUTY":  {"zone_name": "Clean Beauty",       "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
    "MAKEUP":        {"zone_name": "Makeup Counter",     "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
    "ACCESSORIES":   {"zone_name": "Accessories Wall",   "zone_type": "DISPLAY", "is_revenue_zone": "Yes"},
    "FRAGRANCE":     {"zone_name": "Fragrance Corner",   "zone_type": "DISPLAY", "is_revenue_zone": "Yes"},
    "FOH":           {"zone_name": "Front of House",     "zone_type": "DISPLAY", "is_revenue_zone": "No"},
    "BILLING":       {"zone_name": "Billing Counter",    "zone_type": "BILLING", "is_revenue_zone": "Yes"},
    "CASH_COUNTER":  {"zone_name": "Cash Counter Queue", "zone_type": "BILLING", "is_revenue_zone": "Yes"},
    "ENTRY":         {"zone_name": "Store Entrance",     "zone_type": "ENTRY",   "is_revenue_zone": "No"},
    # Store 2 zones
    "HAIRCARE":      {"zone_name": "Haircare Aisle",     "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
    "WALL_UNIT":     {"zone_name": "Wall Unit Display",  "zone_type": "SHELF",   "is_revenue_zone": "Yes"},
}


# ─── Detection Thresholds ────────────────────────────────────────────────────

DETECTION_CONFIDENCE_THRESHOLD = 0.3  # Don't suppress low confidence — flag them
PERSON_CLASS_ID = 0  # COCO class ID for "person"

# Tracking
TRACK_BUFFER = 90       # Frames to keep lost tracks (3 seconds at 30fps)
MATCH_THRESHOLD = 0.7   # ByteTrack association threshold

# Dwell
DWELL_THRESHOLD_MS = 30000  # 30 seconds for zone_dwell events
DWELL_EMIT_INTERVAL_MS = 30000  # Emit zone_dwell every 30s of continued dwell

# Re-entry
REENTRY_SIMILARITY_THRESHOLD = 0.7  # Cosine similarity for re-ID matching
REENTRY_TIME_WINDOW_S = 300  # 5 minutes — max gap for re-entry detection

# Staff detection
STAFF_PRESENCE_THRESHOLD = 0.5  # Present in >50% of clip duration -> likely staff
STAFF_ZONE_COUNT_THRESHOLD = 3  # Appears in 3+ zones -> likely staff

# Frame processing
FRAME_SKIP = 2  # Process every Nth frame for speed (effectively 15fps from 30fps)

# Queue
QUEUE_ZONE_NAME = "BILLING"

# POS correlation
POS_CORRELATION_WINDOW_MIN = 5  # 5-minute window for POS correlation
