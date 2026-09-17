"""
Pose capture loop for PTZ cameras (pyro_camera_api).

From a starting preset, for each pose: capture → save locally → store the
current position as that preset → rotate by `step_deg`.

CLI:
    python capture_poses.py --pi-ip 192.168.255.166 --cam <CAM_IP> \
        --start-pose 20 --step 12.5 --n 35
"""

import argparse
import time
from pathlib import Path

CAPTURES_DIR = Path(__file__).parent / "captures"


def pose_dir(pi_ip: str, cam_ip: str) -> Path:
    return CAPTURES_DIR / pi_ip / cam_ip / "images"


def capture_one(client, cam_ip: str, out_dir: Path, pose: int,
                width: int = 1280, retries: int = 3, retry_delay: float = 3.0) -> Path:
    """Capture and save pose_NN.jpg. Retries: captures drop over VPN."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pose_{pose:02d}.jpg"
    for attempt in range(1, retries + 1):
        try:
            client.capture_image(cam_ip, anonymize=False, width=width).save(path, quality=95)
            return path
        except Exception:
            if attempt == retries:
                raise
            time.sleep(retry_delay)


def capture_poses(client, cam_ip: str, out_dir: Path, start_pose: int = 20,
                  step_deg: float = 12.5, n_captures: int = 35,
                  direction: str = "Right", width: int = 1280,
                  settle: float = 2.0, on_pose=None):
    """Go to `start_pose`, then capture/save/set_preset/rotate `n_captures` times."""
    client.goto_preset(cam_ip, pose_id=start_pose, speed=64)
    time.sleep(3)

    paths = []
    for i in range(n_captures):
        pose = start_pose + i
        if i:
            client.move_by_degrees(cam_ip, direction=direction, degrees=step_deg)
            time.sleep(settle)
        path = capture_one(client, cam_ip, out_dir, pose, width=width)
        client.set_preset(cam_ip, idx=pose)
        paths.append(path)
        if on_pose:
            on_pose(i, pose, path)
    return paths


def _self_check():
    import tempfile
    from PIL import Image

    class FakeClient:
        def __init__(self):
            self.moves, self.presets, self.goto = [], [], None

        def goto_preset(self, cam_ip, pose_id, speed=50):
            self.goto = pose_id

        def move_by_degrees(self, cam_ip, direction, degrees, speed=None):
            self.moves.append((direction, degrees))

        def capture_image(self, cam_ip, anonymize=True, width=None):
            return Image.new("RGB", (width or 8, 8))

        def set_preset(self, cam_ip, idx=None):
            self.presets.append(idx)

    c = FakeClient()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        paths = capture_poses(c, "1.2.3.4", out, start_pose=20, step_deg=12.5,
                              n_captures=3, settle=0, width=1280)
    assert c.goto == 20
    assert c.moves == [("Right", 12.5)] * 2, c.moves          # n-1 moves
    assert c.presets == [20, 21, 22], c.presets
    assert [p.name for p in paths] == ["pose_20.jpg", "pose_21.jpg", "pose_22.jpg"]
    print("self-check ok")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pi-ip", default="192.168.255.166")
    p.add_argument("--cam", required=True)
    p.add_argument("--start-pose", type=int, default=20)
    p.add_argument("--step", type=float, default=12.5)
    p.add_argument("--n", type=int, default=35)
    p.add_argument("--direction", default="Right", choices=["Left", "Right"])
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args()

    if args.self_check:
        return _self_check()

    from pyro_camera_api_client.client import PyroCameraAPIClient
    client = PyroCameraAPIClient(f"http://{args.pi_ip}:8081", timeout=60.0)
    client.stop_patrol(args.cam)
    client.start_stream(args.cam)
    time.sleep(2)
    try:
        capture_poses(client, args.cam, pose_dir(args.pi_ip, args.cam),
                      start_pose=args.start_pose, step_deg=args.step,
                      n_captures=args.n, direction=args.direction, width=args.width,
                      on_pose=lambda i, pose, path: print(f"  {i+1}/{args.n} → {path.name}"))
    finally:
        client.stop_stream()


if __name__ == "__main__":
    main()
