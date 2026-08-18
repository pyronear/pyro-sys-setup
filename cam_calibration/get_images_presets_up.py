"""
Capture calibration images at the saved sweep presets, straight then tilted up.

For each camera returned by camera_infos, the script:
  1. Stops any ongoing patrol
  2. For each preset pose written by the sweep (FIRST_POSE..LAST_POSE):
       goto preset -> sleep -> capture
       tilt Up for 2 s at speed 50 -> sleep -> capture
  3. Captures one image at each active patrol pose (camera_infos "poses")

Images are saved with the capture timestamp in the file name:
    captures/<PI_IP>/<camera_ip>/images_sweep/pose_<N>_<YYYYmmddHHMMSS>.jpg  (straight)
    captures/<PI_IP>/<camera_ip>/images_up/pose_<N>_<YYYYmmddHHMMSS>.jpg     (tilted up)
    captures/<PI_IP>/<camera_ip>/images_patrol/pose_<N>_<YYYYmmddHHMMSS>.jpg (patrol poses)
("images_sweep", not "images": the latter belongs to the pose setup app.)
A manifest.csv per camera also records image, pose, kind and ISO datetime.

Usage:
    python get_images_presets_up.py                      # all cameras
    python get_images_presets_up.py --cam 192.168.1.11   # single camera
"""

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from pyro_camera_api_client.client import PyroCameraAPIClient

from get_images_calibration import FIRST_SAVE_POSE, STEP_DEGREES, TOTAL_DEGREES

# Paris time for now — adapt for sites outside metropolitan France
# (site time zone, or UTC everywhere plus conversion at analysis time).
TZ = ZoneInfo("Europe/Paris")

# ── config ────────────────────────────────────────────────────────────────────
PI_IP = "192.168.255.38"

# Presets written by the sweep: same first pose, one per sweep step.
FIRST_POSE = FIRST_SAVE_POSE
LAST_POSE = FIRST_POSE + int(TOTAL_DEGREES // STEP_DEGREES)
PRESET_SPEED = 50
FIRST_GOTO_SLEEP = 4             # the first preset can be a long travel
SLEEP_AFTER_GOTO = 2             # the camera ignores PTZ ops sent too soon after ToPos
TILT_UP_DURATION = 2             # seconds
TILT_UP_SPEED = 50
SLEEP_AFTER_TILT = 1
ACTIVE_POSE_SLEEP = 3            # patrol poses can be far apart: longer travel
IMAGE_WIDTH = 1280


def capture_and_save(client: PyroCameraAPIClient, camera_ip: str, out_dir: Path,
                     manifest: list, pose: int, kind: str,
                     retries: int = 3, retry_delay: float = 3.0):
    """Capture one frame; the file name embeds the capture timestamp:
    pose_<NN>_<YYYYmmddHHMMSS>.jpg (format read by calibrate_azimuth.py)."""
    log = make_log(camera_ip)
    for attempt in range(1, retries + 1):
        try:
            captured_at = datetime.now(TZ)
            img = client.capture_image(camera_ip, anonymize=False, width=IMAGE_WIDTH)
            out = out_dir / f"pose_{pose:02d}_{captured_at:%Y%m%d%H%M%S}.jpg"
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out, quality=95)
            manifest.append({
                "image": f"{out.parent.name}/{out.name}", "camera": camera_ip,
                "pose": pose, "kind": kind, "datetime": captured_at.isoformat(),
            })
            log(f"saved {out.parent.name}/{out.name}")
            return img
        except Exception as e:
            log(f"capture failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(retry_delay)
    log(f"skipping pose_{pose:02d} ({kind}) after {retries} failed attempts")
    return None


def write_manifest(base: Path, manifest: list) -> None:
    if not manifest:
        return
    with open(base / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)


def make_log(camera_ip: str):
    return lambda msg: print(f"[{camera_ip}] {msg}", flush=True)


def frames_differ(a, b, threshold: float = 3.0) -> bool:
    """Mean absolute gray-level difference — detects whether the camera moved."""
    if a is None or b is None:
        return True
    ga = np.asarray(a.convert("L"), dtype=np.int16)
    gb = np.asarray(b.convert("L"), dtype=np.int16)
    return float(np.abs(ga - gb).mean()) > threshold


def run_camera(client: PyroCameraAPIClient, pi_ip: str, cam: dict,
               last_pose: int = LAST_POSE) -> None:
    cam_ip = cam["camera_id"]
    log = make_log(cam_ip)
    active_poses = cam.get("poses", []) or []
    log(f"({cam.get('name', '?')}) — active poses: {active_poses}")
    base = Path("captures") / pi_ip / cam_ip
    manifest: list = []  # one per camera thread: no lock needed

    log("stopping patrol")
    try:
        client.stop_patrol(cam_ip)
        time.sleep(2)
    except Exception as e:
        log(f"warning: stop_patrol failed ({e})")

    for pose in range(FIRST_POSE, last_pose + 1):
        log(f"pose {pose} ({pose - FIRST_POSE + 1}/{last_pose - FIRST_POSE + 1})")
        client.goto_preset(cam_ip, pose_id=pose, speed=PRESET_SPEED)
        time.sleep(FIRST_GOTO_SLEEP if pose == FIRST_POSE else SLEEP_AFTER_GOTO)
        # "images_sweep" and not "images": the latter is used by the pose setup
        # app, the two sets of captures must not be mixed.
        straight = capture_and_save(client, cam_ip, base / "images_sweep",
                                    manifest, pose, "straight")

        # The camera silently ignores PTZ ops sent too soon after ToPos:
        # verify the view actually changed, retry the tilt otherwise.
        for attempt in range(1, 4):
            log(f"  tilt Up {TILT_UP_DURATION}s @ speed {TILT_UP_SPEED}"
                + (f" (retry {attempt})" if attempt > 1 else ""))
            client.move_for_duration(cam_ip, direction="Up",
                                     duration=TILT_UP_DURATION, speed=TILT_UP_SPEED)
            time.sleep(SLEEP_AFTER_TILT)
            up = capture_and_save(client, cam_ip, base / "images_up", manifest, pose, "up")
            if frames_differ(straight, up):
                break
            log("  tilt had no effect (identical image), retrying…")
        else:
            log(f"  warning: the camera did not move for pose {pose} (up)")

    for pose in active_poses:
        log(f"active pose {pose}")
        client.goto_preset(cam_ip, pose_id=pose, speed=PRESET_SPEED)
        time.sleep(ACTIVE_POSE_SLEEP)
        capture_and_save(client, cam_ip, base / "images_patrol", manifest, pose, "patrol")

    write_manifest(base, manifest)
    log(f"done — {len(manifest)} timestamped captures in manifest.csv, patrol left stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture preset poses straight + tilted up on every camera")
    parser.add_argument("--pi-ip", default=PI_IP)
    parser.add_argument("--cam", default=None, help="Single camera IP (default: all)")
    parser.add_argument("--last-pose", type=int, default=LAST_POSE,
                        help=f"last sweep preset (default {LAST_POSE}, from the sweep configuration)")
    args = parser.parse_args()

    client = PyroCameraAPIClient(f"http://{args.pi_ip}:8081", timeout=30.0)
    cameras = client.get_camera_infos().get("cameras", [])
    print(f"Found {len(cameras)} camera(s): {[c['camera_id'] for c in cameras]}")
    if args.cam:
        cameras = [c for c in cameras if c["camera_id"] == args.cam]
        if not cameras:
            raise SystemExit(f"Camera {args.cam} not found")

    # One thread per camera: independent hardware, per-camera server lock,
    # so the whole capture takes the time of a single camera.
    def safe_run(cam: dict) -> None:
        try:
            run_camera(client, args.pi_ip, cam, last_pose=args.last_pose)
        except Exception as e:
            print(f"[{cam['camera_id']}] Error: {e}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, len(cameras))) as pool:
        list(pool.map(safe_run, cameras))


if __name__ == "__main__":
    main()
