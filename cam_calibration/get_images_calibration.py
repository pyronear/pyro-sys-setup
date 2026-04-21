"""
Capture calibration images from all PTZ cameras via the pyro-engine camera API.

For each camera, the script:
  1. Stops any ongoing patrol
  2. Moves to an initial preset position
  3. Sweeps TOTAL_DEGREES in STEP_DEGREES increments, saving a JPEG at each step

Images are saved to:
    captures/<PI_IP>/<camera_ip>/images/pose_<N>.jpg

Usage:
    python get_images_calibration.py
    python get_images_calibration.py --pi-ip 192.168.255.62 --cam 169.254.7.1
"""

import argparse
import time
from pathlib import Path

from pyro_camera_api_client.client import PyroCameraAPIClient

# ── config ────────────────────────────────────────────────────────────────────
PI_IP = "192.168.255.62"
API_BASE = f"http://{PI_IP}:8081"

INITIAL_PRESET = 20       # preset to go to before starting the sweep
FIRST_SAVE_POSE = 30      # pose index for the first saved image
STEP_DEGREES = 20         # degrees between captures
TOTAL_DEGREES = 340       # total rotation — keep below 360 to avoid loop-closure issues in stitching
DIRECTION = "Right"       # "Left" or "Right"
SPEED_LEVEL = 3           # 1..5
SLEEP_AFTER_MOVE = 2      # seconds to wait after each move — avoids motion blur in captured frames
IMAGE_WIDTH = 1280


# ── helpers ───────────────────────────────────────────────────────────────────

def ensure_dirs(pi_ip: str, camera_ip: str) -> Path:
    out_dir = Path("captures") / pi_ip / camera_ip / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def capture_and_save(client: PyroCameraAPIClient, camera_ip: str,
                     out_dir: Path, pose_id: int, width: int = IMAGE_WIDTH,
                     retries: int = 3, retry_delay: float = 3.0):
    for attempt in range(1, retries + 1):
        try:
            img = client.capture_image(camera_ip, anonymize=False, width=width)
            p = out_dir / f"pose_{pose_id:02d}.jpg"
            img.save(p, quality=95)
            print(f"  saved {p.name}")
            return
        except Exception as e:
            print(f"  capture failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(retry_delay)
    print(f"  skipping pose {pose_id} after {retries} failed attempts")


def capture_static(client: PyroCameraAPIClient, pi_ip: str, cam: dict):
    cam_ip = cam["camera_id"]
    name = cam.get("name", cam_ip)
    print(f"\n{'='*40}\n{cam_ip} ({name}) [static]")
    out_dir = ensure_dirs(pi_ip, cam_ip)
    capture_and_save(client, cam_ip, out_dir, pose_id=0)
    print("  done")


def sweep_ptz(client: PyroCameraAPIClient, pi_ip: str, cam: dict):
    cam_ip = cam["camera_id"]
    name = cam.get("name", cam_ip)
    print(f"\n{'='*40}\n{cam_ip} ({name}) [ptz]")
    out_dir = ensure_dirs(pi_ip, cam_ip)
    steps = int(TOTAL_DEGREES // STEP_DEGREES)

    print("  stopping patrol")
    try:
        client.stop_patrol(cam_ip)
        time.sleep(2)
    except Exception as e:
        print(f"  warning: stop_patrol failed ({e})")

    print(f"  moving to initial preset {INITIAL_PRESET}")
    client.move_camera(cam_ip, pose_id=INITIAL_PRESET, speed=SPEED_LEVEL)
    time.sleep(2)

    current_pose = FIRST_SAVE_POSE

    try:
        client.set_preset(cam_ip, idx=current_pose)
    except Exception as e:
        print(f"  warning: set_preset failed at pose {current_pose} ({e})")

    print(f"  capturing initial frame (pose {current_pose})")
    capture_and_save(client, cam_ip, out_dir, current_pose)

    for i in range(steps):
        print(f"  step {i+1}/{steps} — rotating {STEP_DEGREES}° {DIRECTION}")
        info = client.move_camera(cam_ip, direction=DIRECTION,
                                  degrees=STEP_DEGREES, speed=SPEED_LEVEL)
        print(f"    {info}")

        if SLEEP_AFTER_MOVE:
            time.sleep(SLEEP_AFTER_MOVE)

        current_pose += 1
        try:
            client.set_preset(cam_ip, idx=current_pose)
        except Exception as e:
            print(f"  warning: set_preset failed at pose {current_pose} ({e})")

        capture_and_save(client, cam_ip, out_dir, current_pose)

    print(f"  sweep complete — {current_pose - FIRST_SAVE_POSE + 1} images saved to {out_dir}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Capture PTZ calibration images")
    parser.add_argument("--pi-ip", default=PI_IP)
    parser.add_argument("--cam", default=None, help="Single camera IP (default: all)")
    args = parser.parse_args()

    api_base = f"http://{args.pi_ip}:8081"
    client = PyroCameraAPIClient(api_base, timeout=30.0)

    cameras = client.get_camera_infos().get("cameras", [])
    print(f"Found {len(cameras)} camera(s)")

    if args.cam:
        cameras = [c for c in cameras if c["camera_id"] == args.cam]
        if not cameras:
            raise SystemExit(f"Camera {args.cam} not found")

    for cam in cameras:
        try:
            if cam.get("type") == "ptz":
                sweep_ptz(client, args.pi_ip, cam)
            else:
                capture_static(client, args.pi_ip, cam)
        except Exception as e:
            print(f"Error on {cam['camera_id']}: {e}")
            continue


if __name__ == "__main__":
    main()
