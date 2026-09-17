"""
Pure helpers for the pixel-shift measurement page (page 5).

Measuring the same landmark in two consecutive poses gives the real rotation
the camera performed, which move_by_degrees only approximates.

Self-check:
    uv run python pixel_shift.py
"""

import math
import re
from pathlib import Path
from typing import NamedTuple

POSE_RE = re.compile(r"pose_(\d+)(?:_(\d{14}))?\.jpg$")


def latest_per_pose(folder) -> dict[int, Path]:
    """Map pose index -> newest image. Runs accumulate in the same folder
    (names carry a timestamp), so keep the most recent capture per pose."""
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


def pixel_to_angle(x_px: float, image_w: int, fov_deg: float) -> float:
    """Angle of a pixel column from the optical axis, rectilinear lens.

    Not x * fov / width: that linear form drifts up to 0.8° mid-frame at a
    54° FOV — 3.6% of a 22.5° step, i.e. the error we are trying to measure."""
    f = (image_w / 2) / math.tan(math.radians(fov_deg) / 2)
    return math.degrees(math.atan((x_px - image_w / 2) / f))


def rotation_between(xa: float, xb: float, image_w: int, fov_deg: float) -> float:
    """Pan angle between two poses from one landmark seen in both.

    Positive = the camera panned Right (the scene slid left in the frame)."""
    return pixel_to_angle(xa, image_w, fov_deg) - pixel_to_angle(xb, image_w, fov_deg)


class Baseline(NamedTuple):
    """One landmark seen in two poses n_steps apart, after `turns` full circles."""
    xa: float
    xb: float
    image_w: int
    n_steps: int
    turns: int = 0

    def step_angle(self, fov_deg: float) -> float:
        """Per-step pan implied by this baseline at a given FOV."""
        observed = rotation_between(self.xa, self.xb, self.image_w, fov_deg)
        return (observed + 360.0 * self.turns) / self.n_steps


def solve_fov(short: Baseline, loop: Baseline, lo: float = 20.0,
              hi: float = 120.0, tol: float = 1e-9) -> tuple[float, float] | None:
    """Fit the real horizontal FOV from a short baseline and a loop-closing one.

    The datasheet FOV is a nominal figure; the true one is what makes both
    measurements agree on the same per-step angle. Each baseline says

        n * theta - 360 * turns = angle(xa, fov) - angle(xb, fov)

    A short pair (turns=0) pins theta as a function of fov. A pair that has gone
    right round (turns=1) is 360° of lever arm on the same theta, so the fov that
    reconciles the two is strongly constrained. Returns (fov, theta), or None when
    no solution exists in [lo, hi].

    No solution is a clear signal (wrong `turns`, landmarks far apart), but the
    converse does not hold: a mismatched landmark usually still fits *some* fov.
    Cross-check the result against a second landmark before trusting it.
    """
    def residual(fov: float) -> float:
        return loop.step_angle(fov) - short.step_angle(fov)

    f_lo, f_hi = residual(lo), residual(hi)
    if f_lo == 0.0:
        return lo, short.step_angle(lo)
    if f_hi == 0.0:
        return hi, short.step_angle(hi)
    if f_lo * f_hi > 0:
        return None

    # residual is monotonic in fov (checked in demo()), so plain bisection is
    # enough — no need to pull scipy in for one scalar root
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if residual(mid) * f_lo > 0:
            lo, f_lo = mid, residual(mid)
        else:
            hi = mid
    fov = (lo + hi) / 2
    return fov, short.step_angle(fov)


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

    # a landmark crossing the whole frame means the camera panned by one FOV
    assert abs(rotation_between(W, 0, W, FOV) - FOV) < 1e-9
    assert rotation_between(900, 400, W, FOV) > 0, "scene sliding left = pan Right"
    assert abs(rotation_between(700, 700, W, FOV)) < 1e-9, "no move, no rotation"

    # the linear form would answer 21.17 here: 0.35° adrift, enough to fake a
    # step error that is not there
    assert abs(rotation_between(1180, 680, W, FOV) - 21.52) < 0.01

    # ── the solver, against a synthetic camera whose truth we know ────────────
    TRUE_FOV, TRUE_STEP = 51.3, 22.17   # neither the datasheet 54.2 nor 22.5

    def project(angle_from_axis: float) -> float:
        """Inverse of pixel_to_angle: where a landmark at this angle lands."""
        f = (W / 2) / math.tan(math.radians(TRUE_FOV) / 2)
        return W / 2 + f * math.tan(math.radians(angle_from_axis))

    def synth(n_steps: int, turns: int, start: float) -> Baseline:
        """Landmark `start`° off-axis in pose A, after n_steps of TRUE_STEP."""
        end = start - (n_steps * TRUE_STEP - 360.0 * turns)
        return Baseline(project(start), project(end), W, n_steps, turns)

    short = synth(1, 0, 10.0)
    loop = synth(16, 1, 10.0)          # 16 * 22.17 = 354.7°, just short of a turn
    got = solve_fov(short, loop)
    assert got is not None, "the synthetic pair must have a solution"
    fov, step = got
    assert abs(fov - TRUE_FOV) < 1e-3, f"fov {fov} != {TRUE_FOV}"
    assert abs(step - TRUE_STEP) < 1e-4, f"step {step} != {TRUE_STEP}"

    # the datasheet FOV would have mis-stated the step by a real margin
    assert abs(short.step_angle(54.2) - TRUE_STEP) > 0.5

    # bisection needs a monotonic residual: verify it over the bracket
    res = [loop.step_angle(f) - short.step_angle(f) for f in range(20, 121)]
    deltas = [b - a for a, b in zip(res, res[1:])]
    assert all(d > 0 for d in deltas) or all(d < 0 for d in deltas), \
        "residual must be monotonic in fov for bisection to be valid"

    # no root inside the bracket -> None rather than a made-up edge value
    assert solve_fov(short, loop, lo=80.0, hi=120.0) is None

    print("pixel_shift: all checks passed")


if __name__ == "__main__":
    demo()
