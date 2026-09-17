"""
Pose capture loop for PTZ cameras (pyro_camera_api).

From a starting preset, for each pose: capture → save locally → store the
current position as that preset → rotate by `step_deg`.

A run starts by deleting the previous images of the folder: a sweep is only
consistent with itself. Names carry the capture time, pose_NN_YYYYmmddHHMMSS.jpg.
A capture that still fails after its retries is skipped, the sweep goes on:
the missing pose just makes one longer step for the calibration page.

`from_presets=True` refreshes the images of poses that already exist on the
camera: go to each preset, capture, next. No rotation by step, presets untouched.

Several cameras on one Pi run at the same time: the API locks per camera, so
they do not wait for each other. No video stream is involved — a capture is a
plain snapshot, and the Pi allows one stream at a time anyway.

CLI:
    python capture_poses.py --pi-ip 192.168.255.166 --cam <CAM_IP> [--cam <CAM_IP_2>] \
        --start-pose 20 --step 12.5 --n 35
"""

import argparse
import threading
import time
from pathlib import Path

from pixel_shift import POSE_RE

CAPTURES_DIR = Path(__file__).parent / "captures"


def pose_dir(pi_ip: str, cam_ip: str) -> Path:
    return CAPTURES_DIR / pi_ip / cam_ip / "images"


def capture_one(client, cam_ip: str, out_dir: Path, pose: int,
                width: int = 1280, retries: int = 3, retry_delay: float = 3.0) -> Path:
    """Capture and save pose_NN_<timestamp>.jpg. Retries: captures drop over VPN."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pose_{pose:02d}_{time.strftime('%Y%m%d%H%M%S')}.jpg"
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
                  settle: float = 2.0, on_pose=None, retry_delay: float = 3.0,
                  from_presets: bool = False):
    """Go to `start_pose`, then capture/save/set_preset/rotate `n_captures` times.
    With `from_presets`, go to each existing preset and capture it instead.

    Returns one path per pose, None where the capture failed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("pose_*.jpg"):
        old.unlink()
    if not from_presets:
        # the presets move: the landmarks clicked on the old images and the
        # calibration built from them are wrong for the new sweep
        for name in ("landmarks.json", "calibration.csv"):
            (out_dir.parent / name).unlink(missing_ok=True)

    if not from_presets:
        client.goto_preset(cam_ip, pose_id=start_pose, speed=64)
        time.sleep(3)

    paths = []
    for i in range(n_captures):
        pose = start_pose + i
        if from_presets:
            client.goto_preset(cam_ip, pose_id=pose, speed=64)
            time.sleep(settle)
        elif i:
            client.move_by_degrees(cam_ip, direction=direction, degrees=step_deg)
            time.sleep(settle)
        try:
            path = capture_one(client, cam_ip, out_dir, pose, width=width,
                               retry_delay=retry_delay)
        except Exception:
            path = None                   # skip, keep the sweep aligned
        if not from_presets:
            client.set_preset(cam_ip, idx=pose)
        paths.append(path)
        if on_pose:
            on_pose(i, pose, path)
    return paths


def capture_in_parallel(client, cam_ips, out_dir_for, on_pose=None, **kw) -> dict:
    """capture_poses on every camera at once. Returns {cam_ip: paths}, or the
    exception for a camera whose run failed. `on_pose(cam_ip, i, pose, path)`
    is called from the capture threads."""
    results = {}

    def run(cam_ip):
        cb = (lambda i, pose, path: on_pose(cam_ip, i, pose, path)) if on_pose else None
        try:
            results[cam_ip] = capture_poses(client, cam_ip, out_dir_for(cam_ip), on_pose=cb, **kw)
        except Exception as e:
            results[cam_ip] = e

    threads = [threading.Thread(target=run, args=(c,), daemon=True) for c in cam_ips]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _self_check():
    import tempfile
    from PIL import Image

    class FakeClient:
        def __init__(self, fail_pose=None):
            self.moves, self.presets, self.goto = [], [], None
            self.fail_pose, self.captures = fail_pose, 0

        def goto_preset(self, cam_ip, pose_id, speed=50):
            self.goto = pose_id
            self.gotos = getattr(self, "gotos", []) + [pose_id]

        def move_by_degrees(self, cam_ip, direction, degrees, speed=None):
            self.moves.append((direction, degrees))

        def capture_image(self, cam_ip, anonymize=True, width=None):
            self.captures += 1
            if len(self.presets) == self.fail_pose:
                raise OSError("dropped over VPN")
            return Image.new("RGB", (width or 8, 8))

        def set_preset(self, cam_ip, idx=None):
            self.presets.append(idx)

    c = FakeClient()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        out = out / "images"
        (out.parent / "landmarks.json").touch()
        (out.parent / "calibration.csv").touch()
        out.mkdir()
        (out / "pose_20_20200101000000.jpg").touch()          # a previous run
        paths = capture_poses(c, "1.2.3.4", out, start_pose=20, step_deg=12.5,
                              n_captures=3, settle=0, width=1280)
        assert sorted(p.name for p in out.glob("*.jpg")) == \
            sorted(p.name for p in paths), "old run must be wiped"
        assert not (out.parent / "landmarks.json").exists(), "a new sweep voids the landmarks"
        assert not (out.parent / "calibration.csv").exists()
    assert c.goto == 20
    assert c.moves == [("Right", 12.5)] * 2, c.moves          # n-1 moves
    assert c.presets == [20, 21, 22], c.presets
    assert [POSE_RE.search(p.name).group(1) for p in paths] == ["20", "21", "22"]
    assert all(POSE_RE.search(p.name).group(2) for p in paths), "names carry a timestamp"

    # a capture that keeps failing is skipped, the sweep and the presets go on
    c = FakeClient(fail_pose=1)
    with tempfile.TemporaryDirectory() as tmp:
        paths = capture_poses(c, "1.2.3.4", Path(tmp), n_captures=3, settle=0,
                              retry_delay=0)
    assert paths[1] is None and paths[0] and paths[2], paths
    assert c.presets == [20, 21, 22] and c.captures == 5, (c.presets, c.captures)

    # refresh from existing presets: go to each one, no move, presets untouched
    c = FakeClient()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "images"
        (out.parent / "landmarks.json").touch()
        paths = capture_poses(c, "1.2.3.4", out, n_captures=3, settle=0,
                              from_presets=True)
        assert (out.parent / "landmarks.json").exists(), "presets unchanged: landmarks stay"
    assert c.gotos == [20, 21, 22] and c.moves == [] and c.presets == [], (c.gotos, c.moves, c.presets)
    assert len(paths) == 3 and all(paths)

    # two cameras at once: both complete, events carry the camera, one failing
    # camera does not take the other down
    class Flaky(FakeClient):
        def goto_preset(self, cam_ip, pose_id, speed=50):
            if cam_ip == "bad":
                raise OSError("no such preset")
            super().goto_preset(cam_ip, pose_id, speed)

    c, events = Flaky(), []
    with tempfile.TemporaryDirectory() as tmp:
        res = capture_in_parallel(c, ["a", "b", "bad"], lambda cam: Path(tmp) / cam / "images",
                                  on_pose=lambda cam, i, p, path: events.append((cam, p)),
                                  n_captures=3, settle=0)
    assert len(res["a"]) == 3 and len(res["b"]) == 3, res
    assert isinstance(res["bad"], OSError), res["bad"]
    assert sorted(events) == sorted([(cam, p) for cam in "ab" for p in (20, 21, 22)]), events
    print("self-check ok")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pi-ip", default="192.168.255.166")
    p.add_argument("--cam", action="append", required=True,
                   help="camera IP, repeat for several cameras captured in parallel")
    p.add_argument("--start-pose", type=int, default=20)
    p.add_argument("--step", type=float, default=12.5)
    p.add_argument("--n", type=int, default=35)
    p.add_argument("--direction", default="Right", choices=["Left", "Right"])
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--from-presets", action="store_true",
                   help="refresh the images of existing presets, no rotation")
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args()

    if args.self_check:
        return _self_check()

    from pyro_camera_api_client.client import PyroCameraAPIClient
    client = PyroCameraAPIClient(f"http://{args.pi_ip}:8081", timeout=60.0)
    for cam in args.cam:
        client.stop_patrol(cam)
    results = capture_in_parallel(
        client, args.cam, lambda cam: pose_dir(args.pi_ip, cam),
        start_pose=args.start_pose, step_deg=args.step, n_captures=args.n,
        direction=args.direction, width=args.width, from_presets=args.from_presets,
        on_pose=lambda cam, i, pose, path: print(
            f"  [{cam}] {i+1}/{args.n} → {path.name if path else 'capture failed, skipped'}"))
    for cam, r in results.items():
        print(f"{cam}: {'ERROR ' + str(r) if isinstance(r, Exception) else f'{sum(p is not None for p in r)}/{len(r)} images'}")


if __name__ == "__main__":
    main()
