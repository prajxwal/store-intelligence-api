"""
Extract sample frames from all video footage (Store 1 + Store 2).
Saves one frame per video at the 30-second mark for visual analysis.
"""

import cv2
import os
import sys

def extract_frame(video_path: str, output_path: str, timestamp_sec: float = 30.0):
    """Extract a single frame from a video at the given timestamp."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  ERROR: Cannot open {video_path}")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    # Clamp to middle of video if requested time is beyond duration
    target_sec = min(timestamp_sec, duration * 0.5)
    target_frame = int(target_sec * fps)

    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()

    if ret:
        cv2.imwrite(output_path, frame)
        h, w = frame.shape[:2]
        print(f"  OK {os.path.basename(video_path)} -> {os.path.basename(output_path)} ({w}x{h}, t={target_sec:.1f}s/{duration:.1f}s)")
        return True
    else:
        print(f"  ERROR: Could not read frame from {video_path}")
        return False


def main():
    dataset_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Dataset")
    frames_dir = os.path.join(dataset_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Store 1 videos
    store1_dir = os.path.join(dataset_dir, "Store 1")
    store1_videos = [
        ("CAM 1 - zone.mp4", "store1_cam1_zone.jpg"),
        ("CAM 2 - zone.mp4", "store1_cam2_zone.jpg"),
        ("CAM 3 - entry.mp4", "store1_cam3_entry.jpg"),
        ("CAM 5 - billing.mp4", "store1_cam5_billing.jpg"),
    ]

    print("\n=== Store 1 (Brigade Bangalore) ===")
    for video_name, frame_name in store1_videos:
        video_path = os.path.join(store1_dir, video_name)
        if os.path.exists(video_path):
            extract_frame(video_path, os.path.join(frames_dir, frame_name))
        else:
            print(f"  SKIP: {video_name} not found")

    # Store 2 videos
    store2_dir = os.path.join(dataset_dir, "Store 2")
    store2_videos = [
        ("entry 1.mp4", "store2_entry1.jpg"),
        ("entry 2.mp4", "store2_entry2.jpg"),
        ("zone.mp4", "store2_zone.jpg"),
        ("billing_area.mp4", "store2_billing.jpg"),
    ]

    print("\n=== Store 2 ===")
    for video_name, frame_name in store2_videos:
        video_path = os.path.join(store2_dir, video_name)
        if os.path.exists(video_path):
            extract_frame(video_path, os.path.join(frames_dir, frame_name))
        else:
            print(f"  SKIP: {video_name} not found")

    # Also extract from old CCTV Footage if it still exists
    old_dir = os.path.join(dataset_dir, "CCTV Footage")
    if os.path.exists(old_dir):
        print("\n=== Old CCTV Footage (for reference) ===")
        for i in range(1, 6):
            video_path = os.path.join(old_dir, f"CAM {i}.mp4")
            if os.path.exists(video_path):
                extract_frame(video_path, os.path.join(frames_dir, f"cam{i}_sample.jpg"))

    print(f"\nAll frames saved to: {frames_dir}")
    print(f"Total frames: {len(os.listdir(frames_dir))}")


if __name__ == "__main__":
    main()
