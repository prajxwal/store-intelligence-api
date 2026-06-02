"""
Main detection pipeline — processes CCTV clips using YOLOv8 + ByteTrack.
Detects people, tracks movement, determines entry/exit direction,
classifies zones, detects staff, and emits structured events.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import cv2
import numpy as np

from ultralytics import YOLO
from tqdm import tqdm

from pipeline.config import (
    STORES, ACTIVE_CAMERAS, STORE_ID, VIDEO_DIR, OUTPUT_DIR,
    DETECTION_CONFIDENCE_THRESHOLD, PERSON_CLASS_ID,
    FRAME_SKIP, DWELL_THRESHOLD_MS, DWELL_EMIT_INTERVAL_MS,
    STAFF_PRESENCE_THRESHOLD, STAFF_ZONE_COUNT_THRESHOLD,
    VIDEO_START_TIMES, TRACK_BUFFER, ZONE_METADATA,
)
from pipeline.emit import EventEmitter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


class PersonTrack:
    """State for a tracked person across frames."""

    def __init__(self, track_id: int, visitor_id: str, first_seen: datetime):
        self.track_id = track_id
        self.visitor_id = visitor_id
        self.first_seen = first_seen
        self.last_seen = first_seen
        self.positions: list[tuple[float, float]] = []  # (cx, cy) centers
        self.current_zone: Optional[str] = None
        self.zone_enter_time: Optional[datetime] = None
        self.zones_visited: set[str] = set()
        self.has_entered: bool = False
        self.has_exited: bool = False
        self.is_staff: bool = False
        self.confidence_scores: list[float] = []
        self.frame_count: int = 0
        self.last_dwell_emit: Optional[datetime] = None
        self.bbox_history: list[tuple[int, int, int, int]] = []  # For ReID

    @property
    def avg_confidence(self) -> float:
        return sum(self.confidence_scores) / len(self.confidence_scores) if self.confidence_scores else 0.0

    @property
    def duration_ms(self) -> int:
        return int((self.last_seen - self.first_seen).total_seconds() * 1000)

    def update(self, cx: float, cy: float, confidence: float, timestamp: datetime, bbox: tuple):
        self.positions.append((cx, cy))
        self.confidence_scores.append(confidence)
        self.last_seen = timestamp
        self.frame_count += 1
        self.bbox_history.append(bbox)
        # Keep last 30 bboxes for memory
        if len(self.bbox_history) > 30:
            self.bbox_history = self.bbox_history[-30:]


def classify_zone_by_camera(camera_id: str, cx: float, cy: float, 
                             frame_w: int, frame_h: int,
                             active_cameras: dict = None) -> Optional[str]:
    """
    Classify which zone a person is in based on camera and position.
    Uses spatial heuristics derived from the store layout.
    """
    cams = active_cameras or ACTIVE_CAMERAS
    cam_config = cams.get(camera_id)
    if not cam_config:
        return None

    nx, ny = cx / frame_w, cy / frame_h  # Normalised coords

    if cam_config.zone_type == "entry":
        return "ENTRY"

    elif cam_config.zone_type == "billing":
        if camera_id.startswith("S2_"):
            # Store 2: billing_area.mp4 — cash counter is center-top of frame
            if ny < 0.6:
                return "CASH_COUNTER"
            else:
                return "MAKEUP"
        else:
            # Store 1: CAM 5
            if nx < 0.5:
                return "CASH_COUNTER"
            else:
                return "ACCESSORIES"

    elif cam_config.zone_type == "floor":
        if camera_id == "CAM_01":
            # Store 1: Skincare wall
            if ny < 0.4:
                if nx < 0.33:
                    return "KOREAN_BEAUTY"
                elif nx < 0.66:
                    return "CLEAN_BEAUTY"
                else:
                    return "SKINCARE"
            else:
                return "FOH"

        elif camera_id == "CAM_02":
            # Store 1: Makeup wall
            if ny < 0.5:
                if nx > 0.3:
                    return "MAKEUP"
                else:
                    return "ACCESSORIES"
            else:
                if nx < 0.3:
                    return "FRAGRANCE"
                else:
                    return "MAKEUP"

        elif camera_id == "S2_ZONE":
            # Store 2: Narrow aisle — left wall vs right wall
            if nx < 0.5:
                return "SKINCARE"
            else:
                return "HAIRCARE"

    return cam_config.zones[0] if cam_config.zones else None


def detect_entry_exit(track: PersonTrack, camera_id: str, 
                       frame_h: int, entry_line_y: int = 400) -> Optional[str]:
    """
    Determine if a person crossed the entry threshold.
    For the entry camera (CAM_03):
    - Movement from bottom to top = ENTRY (coming inside)
    - Movement from top to bottom = EXIT (going outside)
    """
    if len(track.positions) < 5:
        return None

    # Use recent positions to determine direction
    recent = track.positions[-10:]
    start_y = np.mean([p[1] for p in recent[:3]])
    end_y = np.mean([p[1] for p in recent[-3:]])

    # Normalise
    start_ny = start_y / frame_h
    end_ny = end_y / frame_h
    threshold_ny = entry_line_y / frame_h

    # Significant vertical movement crossing the threshold
    if abs(start_ny - end_ny) > 0.05:
        if start_ny > threshold_ny and end_ny < threshold_ny:
            return "ENTRY"  # Moving from outside (bottom) to inside (top)
        elif start_ny < threshold_ny and end_ny > threshold_ny:
            return "EXIT"   # Moving from inside (top) to outside (bottom)

    return None


def classify_staff(tracks: dict[int, PersonTrack], total_frames: int, fps: float) -> set[int]:
    """
    Classify which tracks are staff based on:
    1. Present for >50% of clip duration
    2. Appears in 3+ different zones
    3. Has high frame count relative to clip length
    """
    staff_ids = set()
    total_duration = total_frames / fps if fps > 0 else 1

    for track_id, track in tracks.items():
        track_duration = track.duration_ms / 1000.0
        presence_ratio = track_duration / total_duration if total_duration > 0 else 0

        is_long_present = presence_ratio > STAFF_PRESENCE_THRESHOLD
        visits_many_zones = len(track.zones_visited) >= STAFF_ZONE_COUNT_THRESHOLD
        high_frame_count = track.frame_count > (total_frames * 0.3)

        if (is_long_present and visits_many_zones) or high_frame_count:
            staff_ids.add(track_id)
            track.is_staff = True
            logger.debug(f"Track {track_id} classified as STAFF "
                        f"(presence={presence_ratio:.1%}, zones={len(track.zones_visited)})")

    return staff_ids


def process_camera(
    model: YOLO,
    camera_id: str,
    video_path: str,
    emitter: EventEmitter,
    start_time_str: str,
) -> dict:
    """Process a single camera feed through the detection pipeline."""
    
    cam_config = ACTIVE_CAMERAS[camera_id]
    logger.info(f"Processing {camera_id} ({cam_config.zone_type}): {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video: {video_path}")
        return {"error": "Cannot open video"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_time = datetime.fromisoformat(start_time_str)

    logger.info(f"  Video: {frame_w}x{frame_h} @ {fps}fps, {total_frames} frames "
                f"({total_frames/fps:.1f}s)")

    # State
    tracks: dict[int, PersonTrack] = {}
    visitor_counter = 0
    entry_count = 0
    exit_count = 0
    frame_idx = 0
    prev_track_ids: set[int] = set()

    pbar = tqdm(total=total_frames, desc=f"  {camera_id}", unit="frame")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        pbar.update(1)

        # Skip frames for speed
        if frame_idx % FRAME_SKIP != 0:
            continue

        # Current timestamp
        elapsed_s = frame_idx / fps
        current_time = start_time + timedelta(seconds=elapsed_s)

        # Run YOLOv8 tracking
        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[PERSON_CLASS_ID],
            conf=DETECTION_CONFIDENCE_THRESHOLD,
            verbose=False,
        )

        current_track_ids: set[int] = set()

        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes
            track_ids = boxes.id.int().cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            xyxy = boxes.xyxy.cpu().numpy()

            for i, track_id in enumerate(track_ids):
                current_track_ids.add(track_id)
                conf = confidences[i]
                x1, y1, x2, y2 = xyxy[i]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                bbox = (int(x1), int(y1), int(x2), int(y2))

                # Create or update track
                if track_id not in tracks:
                    visitor_counter += 1
                    visitor_id = f"ID_{60000 + visitor_counter}"
                    tracks[track_id] = PersonTrack(track_id, visitor_id, current_time)

                track = tracks[track_id]
                track.update(cx, cy, conf, current_time, bbox)

                # Zone classification
                zone = classify_zone_by_camera(camera_id, cx, cy, frame_w, frame_h)

                if zone and zone != track.current_zone:
                    # Zone transition detected
                    old_zone = track.current_zone

                    # Emit zone_exited for old zone
                    if old_zone and old_zone != "ENTRY":
                        dwell = int((current_time - track.zone_enter_time).total_seconds() * 1000) \
                                if track.zone_enter_time else 0
                        emitter.emit(emitter.create_zone_event(
                            camera_id=camera_id,
                            track_id=track.track_id,
                            event_type="zone_exited",
                            timestamp=current_time,
                            zone=old_zone,
                            hotspot_x=cx,
                            hotspot_y=cy,
                            confidence=conf,
                        ))

                    # Emit zone_entered for new zone
                    if zone != "ENTRY":
                        track.zones_visited.add(zone)
                        emitter.emit(emitter.create_zone_event(
                            camera_id=camera_id,
                            track_id=track.track_id,
                            event_type="zone_entered",
                            timestamp=current_time,
                            zone=zone,
                            hotspot_x=cx,
                            hotspot_y=cy,
                            confidence=conf,
                        ))

                        # Check if billing zone → emit queue event
                        if zone in ("BILLING", "CASH_COUNTER"):
                            # Count people currently in billing zone
                            queue_depth = sum(
                                1 for t in tracks.values()
                                if t.current_zone in ("BILLING", "CASH_COUNTER")
                                   and t.track_id != track_id
                            )
                            # Store join time for later queue_completed event
                            track.queue_join_time = current_time
                            track.queue_position = queue_depth + 1

                    track.current_zone = zone
                    track.zone_enter_time = current_time

                # Check for dwell events (30s+ in same zone)
                if (track.current_zone and track.current_zone != "ENTRY" 
                    and track.zone_enter_time):
                    dwell_ms = int((current_time - track.zone_enter_time).total_seconds() * 1000)
                    
                    if dwell_ms >= DWELL_THRESHOLD_MS:
                        # Check if we should emit (every 30s)
                        should_emit = (
                            track.last_dwell_emit is None or
                            (current_time - track.last_dwell_emit).total_seconds() * 1000 >= DWELL_EMIT_INTERVAL_MS
                        )
                        if should_emit:
                            emitter.emit(emitter.create_event(
                                camera_id=camera_id,
                                visitor_id=track.visitor_id,
                                event_type="zone_dwell",
                                timestamp=current_time,
                                zone_id=track.current_zone,
                                dwell_ms=dwell_ms,
                                confidence=conf,
                            ))
                            track.last_dwell_emit = current_time

                # Entry/Exit detection (entry camera only)
                if cam_config.zone_type == "entry":
                    direction = detect_entry_exit(
                        track, camera_id, frame_h,
                        entry_line_y=cam_config.entry_line_y or 400,
                    )
                    if direction == "ENTRY" and not track.has_entered:
                        track.has_entered = True
                        entry_count += 1
                        emitter.emit(emitter.create_entry_exit_event(
                            camera_id=camera_id,
                            visitor_id=track.visitor_id,
                            event_type="entry",
                            timestamp=current_time,
                            confidence=conf,
                        ))
                    elif direction == "EXIT" and not track.has_exited:
                        track.has_exited = True
                        exit_count += 1
                        # Emit queue_completed if they were in billing
                        if hasattr(track, 'queue_join_time') and track.queue_join_time:
                            wait_s = int((current_time - track.queue_join_time).total_seconds())
                            emitter.emit(emitter.create_queue_event(
                                camera_id=camera_id,
                                track_id=track.track_id,
                                event_type="queue_completed",
                                zone="BILLING",
                                queue_join_ts=track.queue_join_time,
                                queue_exit_ts=current_time,
                                wait_seconds=wait_s,
                                queue_position_at_join=getattr(track, 'queue_position', 1),
                                abandoned=False,
                            ))
                        emitter.emit(emitter.create_entry_exit_event(
                            camera_id=camera_id,
                            visitor_id=track.visitor_id,
                            event_type="exit",
                            timestamp=current_time,
                            confidence=conf,
                        ))

        # Detect lost tracks → potential exits
        lost_ids = prev_track_ids - current_track_ids
        for lost_id in lost_ids:
            if lost_id in tracks:
                track = tracks[lost_id]
                # If track was in a zone, emit ZONE_EXIT
                if track.current_zone and track.current_zone != "ENTRY":
                    dwell = int((current_time - track.zone_enter_time).total_seconds() * 1000) \
                            if track.zone_enter_time else 0
                    emitter.emit(emitter.create_zone_event(
                        camera_id=camera_id,
                        track_id=track.track_id,
                        event_type="zone_exited",
                        timestamp=current_time,
                        zone=track.current_zone,
                        confidence=track.avg_confidence,
                    ))
                    # If leaving billing zone → queue_abandoned
                    if track.current_zone in ("BILLING", "CASH_COUNTER"):
                        if hasattr(track, 'queue_join_time') and track.queue_join_time:
                            wait_s = int((current_time - track.queue_join_time).total_seconds())
                            emitter.emit(emitter.create_queue_event(
                                camera_id=camera_id,
                                track_id=track.track_id,
                                event_type="queue_abandoned",
                                zone="BILLING",
                                queue_join_ts=track.queue_join_time,
                                queue_exit_ts=current_time,
                                wait_seconds=wait_s,
                                queue_position_at_join=getattr(track, 'queue_position', 1),
                                abandoned=True,
                            ))

        prev_track_ids = current_track_ids

    pbar.close()
    cap.release()

    # Post-processing: classify staff
    staff_ids = classify_staff(tracks, total_frames, fps)
    
    # Update staff flag on already-emitted events won't be possible retroactively,
    # but we mark the tracks for the stats
    logger.info(f"  {camera_id} complete: {len(tracks)} tracks, "
                f"{entry_count} entries, {exit_count} exits, "
                f"{len(staff_ids)} staff detected")

    return {
        "camera_id": camera_id,
        "total_tracks": len(tracks),
        "entry_count": entry_count,
        "exit_count": exit_count,
        "staff_count": len(staff_ids),
        "total_frames": total_frames,
    }




def run_pipeline(
    store_key: str = "store1",
    model_path: str = "yolov8m.pt",
    api_url: str = "http://localhost:8000",
):
    """Run the complete detection pipeline on all cameras for a given store."""

    store_cfg = STORES.get(store_key)
    if not store_cfg:
        logger.error(f"Unknown store: {store_key}. Available: {list(STORES.keys())}")
        return {}

    video_dir = store_cfg.video_dir
    store_id = store_cfg.store_id
    active_cams = store_cfg.active_cameras
    start_times = store_cfg.video_start_times

    logger.info("=" * 60)
    logger.info("Store Intelligence -- Detection Pipeline")
    logger.info("=" * 60)
    logger.info(f"Store: {store_id} ({store_cfg.store_name})")
    logger.info(f"Video dir: {video_dir}")
    logger.info(f"Cameras: {list(active_cams.keys())}")
    logger.info(f"Model: {model_path}")
    logger.info(f"API: {api_url}")

    # Load YOLO model
    logger.info("Loading YOLOv8 model...")
    model = YOLO(model_path)
    logger.info(f"Model loaded: {model_path}")

    # Initialize emitter
    emitter = EventEmitter(store_id=store_id)

    # Process each customer-facing camera
    results = {}
    start = time.time()

    for camera_id, cam_config in active_cams.items():
        video_path = os.path.join(video_dir, cam_config.file_name)

        if not os.path.exists(video_path):
            logger.warning(f"Video not found: {video_path}")
            continue

        start_time = start_times.get(camera_id, store_cfg.store_date + "T12:00:00")
        result = process_camera(model, camera_id, video_path, emitter, start_time)
        results[camera_id] = result

    # Finalize -- flush remaining events to API
    emitter.finalize()

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"Pipeline complete in {elapsed:.1f}s")
    logger.info(f"Total events: {emitter.total_emitted}")
    for cam_id, res in results.items():
        logger.info(f"  {cam_id}: {res.get('total_tracks', 0)} tracks, "
                    f"{res.get('entry_count', 0)} entries")
    logger.info(f"Output: {emitter.output_file}")
    logger.info("=" * 60)
    logger.info("Tip: Run 'python -m pipeline.load_pos' to load POS data")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Store Intelligence Detection Pipeline")
    parser.add_argument("--store", type=str, default="store1",
                        choices=list(STORES.keys()),
                        help="Store to process (default: store1)")
    parser.add_argument("--model", type=str, default="yolov8m.pt",
                        help="YOLOv8 model path (default: yolov8m.pt)")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000",
                        help="API endpoint URL")
    args = parser.parse_args()

    run_pipeline(
        store_key=args.store,
        model_path=args.model,
        api_url=args.api_url,
    )
