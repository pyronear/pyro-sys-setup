"""
Set up default PTZ poses on every camera behind a pyro-engine Pi.

For each PTZ camera the script:
  1. Stops any ongoing patrol
  2. Moves to preset 10 (the factory/home pose)
  3. Tilts Down 10s @ speed 64 (flips the head to the other side), then
     Down 3s @ speed 3 (fine-tune to the horizon) — mirrors pyro-engine's
     capture_all_positions.py
  4. Shifts Right to land on the sweep start
  5. Captures 8 images at ~(fov - overlap)° steps, saving presets 20..27
  6. Moves to the 4 center presets (22..25) and re-saves them as 0..3
     (mirrors pyro-engine's setup_positions.py)

Images are saved to:
    captures/<pi_ip>/<cam_ip>/default_poses/pose_<N>.jpg

Usage:
    python setup_default_poses.py --pi-ip 192.168.255.178
    python setup_default_poses.py --pi-ip 192.168.255.178 --cam 169.254.7.1
"""

import argparse
import time
from pathlib import Path

from pyro_camera_api_client.client import PyroCameraAPIClient

# ── defaults ──────────────────────────────────────────────────────────────────
PI_IP = "192.168.255.178"

START_PRESET = 10          # preset to land on before tilting
FOV_DEG = 54.2
OVERLAP_DEG = 8.0

# Time-based tilt-down to flip the camera to the other side + fine tune
TILT1_SEC, TILT1_SPEED = 10, 64
TILT2_SEC, TILT2_SPEED = 3, 3

# Pan sweep — seconds derived from PAN_DEG_PER_SEC, matching capture_all_positions.py
PAN_SPEED = 5
PAN_DEG_PER_SEC = 7.1131
CAM_STOP_TIME = 0.3

N_CAPTURES = 8                                # 8 × ~46° ≈ 360° + overlap
SWEEP_FIRST_PRESET = 20                       # presets 20..27
CENTER_FIRST_PRESET = SWEEP_FIRST_PRESET + 2  # presets 22..25 → re-saved as 0..3
N_CENTER = 4

TO_POS_SPEED = 64
SLEEP_AFTER_MOVE = 2

IMAGE_WIDTH = 2560


# ── helpers ───────────────────────────────────────────────────────────────────

def center_shift_seconds(fov: float, overlap: float) -> float:
    """Seconds to shift at PAN_SPEED so that the sweep is centred on preset 10's azimuth."""
    deg = fov / 2 - (4 * fov - 3 * overlap - 180) + overlap / 2
    return deg / PAN_DEG_PER_SEC - CAM_STOP_TIME * 2


def overlap_shift_seconds(fov: float, overlap: float) -> float:
    """Seconds to shift at PAN_SPEED for one step of the sweep (fov - overlap)."""
    return (fov - overlap) / PAN_DEG_PER_SEC - CAM_STOP_TIME


def move_seconds(client: PyroCameraAPIClient, cam_ip: str, direction: str,
                 seconds: float, speed: int):
    """Start moving, sleep, stop — PTZ equivalent of move_in_seconds on ReolinkCamera."""
    if seconds <= 0:
        return
    client.move_camera(cam_ip, direction=direction, speed=speed)
    time.sleep(seconds)
    try:
        client.stop_camera(cam_ip)
    except Exception as e:
        print(f"    warning: stop_camera failed: {e}")


def ensure_dirs(pi_ip: str, cam_ip: str) -> Path:
    out = Path("captures") / pi_ip / cam_ip / "default_poses"
    out.mkdir(parents=True, exist_ok=True)
    return out


def capture_and_save(client: PyroCameraAPIClient, cam_ip: str, out_dir: Path,
                     pose_id: int, retries: int = 3, retry_delay: float = 3.0):
    for attempt in range(1, retries + 1):
        try:
            img = client.capture_image(cam_ip, anonymize=False, width=IMAGE_WIDTH)
            p = out_dir / f"pose_{pose_id:02d}.jpg"
            img.save(p, quality=95)
            print(f"    saved {p.name}")
            return
        except Exception as e:
            print(f"    capture failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(retry_delay)
    print(f"    skipping pose {pose_id} after {retries} failed attempts")


# ── per-camera workflow ───────────────────────────────────────────────────────

def setup_camera(client: PyroCameraAPIClient, pi_ip: str, cam: dict,
                 fov: float, overlap: float):
    cam_ip = cam["camera_id"]
    name = cam.get("name", cam_ip)

    if cam.get("type") != "ptz":
        print(f"\n== {cam_ip} ({name}) [static] — skipping")
        return

    print(f"\n{'=' * 50}\n== {cam_ip} ({name}) [ptz]")
    out_dir = ensure_dirs(pi_ip, cam_ip)
    shift_sec = center_shift_seconds(fov, overlap)
    step_sec = overlap_shift_seconds(fov, overlap)

    print("  stopping patrol")
    try:
        client.stop_patrol(cam_ip)
        time.sleep(2)
    except Exception as e:
        print(f"  warning: stop_patrol failed ({e})")

    print(f"  moving to preset {START_PRESET} (speed {TO_POS_SPEED})")
    client.move_camera(cam_ip, pose_id=START_PRESET, speed=TO_POS_SPEED)
    time.sleep(3)

    print(f"  tilting Down {TILT1_SEC}s @ speed {TILT1_SPEED} (flip to other side)")
    move_seconds(client, cam_ip, "Down", TILT1_SEC, TILT1_SPEED)
    time.sleep(1)

    print(f"  tilting Down {TILT2_SEC}s @ speed {TILT2_SPEED} (fine tune)")
    move_seconds(client, cam_ip, "Down", TILT2_SEC, TILT2_SPEED)
    time.sleep(SLEEP_AFTER_MOVE)

    if shift_sec > 0:
        print(f"  shifting Right {shift_sec:.2f}s to sweep start (speed {PAN_SPEED})")
        move_seconds(client, cam_ip, "Right", shift_sec, PAN_SPEED)
    elif shift_sec < 0:
        print(f"  shifting Left {-shift_sec:.2f}s to sweep start (speed {PAN_SPEED})")
        move_seconds(client, cam_ip, "Left", -shift_sec, PAN_SPEED)
    time.sleep(SLEEP_AFTER_MOVE)

    # ── 360° sweep ────────────────────────────────────────────────────────────
    print(f"\n  --- 360° sweep: {N_CAPTURES} captures, {step_sec:.2f}s/step @ speed {PAN_SPEED} ---")
    for i in range(N_CAPTURES):
        pose_id = SWEEP_FIRST_PRESET + i
        print(f"  [{i + 1}/{N_CAPTURES}] pose {pose_id}")
        capture_and_save(client, cam_ip, out_dir, pose_id)

        try:
            client.set_preset(cam_ip, idx=pose_id)
        except Exception as e:
            print(f"    warning: set_preset({pose_id}) failed: {e}")

        if i < N_CAPTURES - 1:
            print(f"    rotating Right {step_sec:.2f}s (speed {PAN_SPEED})")
            move_seconds(client, cam_ip, "Right", step_sec, PAN_SPEED)
            time.sleep(SLEEP_AFTER_MOVE)

    # ── re-save 4 center presets as 0..3 ──────────────────────────────────────
    print(f"\n  --- 4 center presets: "
          f"{CENTER_FIRST_PRESET}..{CENTER_FIRST_PRESET + N_CENTER - 1} → 0..{N_CENTER - 1} ---")
    for new_idx in range(N_CENTER):
        src = CENTER_FIRST_PRESET + new_idx
        print(f"  moving to preset {src} → re-saving as preset {new_idx}")
        client.move_camera(cam_ip, pose_id=src, speed=TO_POS_SPEED)
        time.sleep(3)

        capture_and_save(client, cam_ip, out_dir, new_idx)

        try:
            client.set_preset(cam_ip, idx=new_idx)
        except Exception as e:
            print(f"    warning: set_preset({new_idx}) failed: {e}")

    print(f"\n  done — images under {out_dir}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Set up default PTZ poses on every camera behind a Pi")
    parser.add_argument("--pi-ip", default=PI_IP)
    parser.add_argument("--cam", default=None, help="Single camera IP (default: all)")
    parser.add_argument("--fov", type=float, default=FOV_DEG, help=f"Camera horizontal FOV (default: {FOV_DEG})")
    parser.add_argument("--overlap", type=float, default=OVERLAP_DEG,
                        help=f"Overlap between captures in degrees (default: {OVERLAP_DEG})")
    args = parser.parse_args()

    client = PyroCameraAPIClient(f"http://{args.pi_ip}:8081", timeout=30.0)

    cameras = client.get_camera_infos().get("cameras", [])
    print(f"Found {len(cameras)} camera(s) behind {args.pi_ip}")

    if args.cam:
        cameras = [c for c in cameras if c["camera_id"] == args.cam]
        if not cameras:
            raise SystemExit(f"Camera {args.cam} not found")

    for cam in cameras:
        cam_ip = cam["camera_id"]
        stream_started = False
        try:
            client.start_stream(cam_ip)
            stream_started = True
            time.sleep(2)
            setup_camera(client, args.pi_ip, cam, args.fov, args.overlap)
        except Exception as e:
            print(f"Error on {cam_ip}: {e}")
        finally:
            if stream_started:
                try:
                    client.stop_stream()
                except Exception as e:
                    print(f"warning: stop_stream failed on {cam_ip}: {e}")


if __name__ == "__main__":
    main()
