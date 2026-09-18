"""
Image naming and lens geometry shared by the capture and calibration pages.

Self-check:
    uv run python pixel_shift.py
"""

import math
import re
from pathlib import Path

POSE_RE = re.compile(r"pose_(\d+)(?:_(\d{14}))?\.jpg$")


def latest_per_pose(folder) -> dict[int, Path]:
    """Map pose index -> newest image. Names carry the capture time, so if a
    folder ever holds several captures of a pose the most recent one wins."""
    best: dict[int, tuple[str, Path]] = {}
    for p in sorted(Path(folder).glob("pose_*.jpg")):
        m = POSE_RE.search(p.name)
        if not m:
            continue
        pose, stamp = int(m.group(1)), m.group(2) or ""
        if pose not in best or stamp >= best[pose][0]:
            best[pose] = (stamp, p)
    return {k: best[k][1] for k in sorted(best)}


def to_native(click: dict, native_w: int, native_h: int) -> tuple[float, float]:
    """streamlit_image_coordinates returns *displayed* coords plus the displayed
    size; rescale to native pixels so the measurement is resolution-independent."""
    return (click["x"] * native_w / click["width"],
            click["y"] * native_h / click["height"])


def focal_px(image_w: int, fov_deg: float) -> float:
    return (image_w / 2) / math.tan(math.radians(fov_deg) / 2)


def pixel_to_angle(x_px: float, image_w: int, fov_deg: float) -> float:
    """Angle of a pixel column from the optical axis, rectilinear lens.

    Not x * fov / width: that linear form drifts up to 0.8° mid-frame at a
    54° FOV — 3.6% of a 22.5° step, i.e. the error we are trying to measure."""
    return math.degrees(math.atan((x_px - image_w / 2) / focal_px(image_w, fov_deg)))


def demo() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for n in ["pose_30_20260917142021.jpg", "pose_30_20260917150000.jpg",
                  "pose_31_20260917142036.jpg", "notapose.jpg"]:
            (Path(d) / n).touch()
        poses = latest_per_pose(d)
        assert list(poses) == [30, 31], poses
        assert poses[30].name.endswith("150000.jpg"), "newest capture must win"
        # untimestamped names (the old sweep layout) still parse
        (Path(d) / "pose_32.jpg").touch()
        assert 32 in latest_per_pose(d)

    # displayed 640px-wide click maps back onto the 1280px native frame
    assert to_native({"x": 320, "y": 180, "width": 640, "height": 360}, 1280, 720) \
        == (640.0, 360.0)

    W, FOV = 1280, 54.2
    assert abs(pixel_to_angle(W / 2, W, FOV)) < 1e-9, "centre is the optical axis"
    assert abs(pixel_to_angle(W, W, FOV) - FOV / 2) < 1e-9, "right edge is +fov/2"
    assert abs(pixel_to_angle(0, W, FOV) + FOV / 2) < 1e-9, "left edge is -fov/2"
    # the linear form would answer 21.17 here: 0.35° adrift, enough to fake a
    # step error that is not there
    assert abs(pixel_to_angle(1180, W, FOV) - pixel_to_angle(680, W, FOV) - 21.52) < 0.01

    print("pixel_shift: all checks passed")


if __name__ == "__main__":
    demo()
