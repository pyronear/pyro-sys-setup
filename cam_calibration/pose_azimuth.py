"""
Azimuth of every pose, measured from the images — no panorama, no datasheet FOV.

The camera does not rotate by the angle it is asked for: move_by_degrees is
duration-driven, so each step carries a systematic bias plus jitter, and a step
can be silently dropped altogether. So every step is measured instead of assumed.

  1. phase correlation between consecutive poses  -> horizontal shift of each step
  2. the sweep overshoots 360°, so pose p0 reappears n steps later. The FOV that
     makes the measured angles sum to exactly 360° over that loop is the real one
  3. azimuths are the cumulative sum of the measured angles, anchored on one
     landmark of known azimuth

A dropped step is therefore absorbed where it happened, instead of shifting every
pose after it.

Self-check:
    uv run python pose_azimuth.py
"""

import math
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from pixel_shift import focal_px, latest_per_pose, pixel_to_angle


def shift_to_angle(dx_px: float, image_w: int, fov_deg: float) -> float:
    """Pan angle for a whole-frame shift of dx_px, rectilinear lens."""
    return math.degrees(math.atan(dx_px / focal_px(image_w, fov_deg)))


# ── step measurement ──────────────────────────────────────────────────────────

# Rows kept for correlation, as a fraction of image height. The sky is worse
# than useless — clouds move between two captures, and it covers most of the
# frame — and the bottom of the frame often holds the mast or roof the camera
# sits on, which is identical in every pose and pulls the correlation onto a
# false zero shift. Per camera: depends on the tilt, adjust on page 1.
BAND = (0.55, 0.92)

# Below this shift the pair reads as "the camera never moved" — a silently
# dropped step. Also the floor for calling a step backward: a dropped step is
# 0 ± noise, and noise must not send it to the re-measure.
STILL_PX = 2.0


def _grey(path: Path, band: tuple[float, float] = BAND) -> np.ndarray:
    im = Image.open(path).convert("L")
    lo, hi = int(band[0] * im.height), int(band[1] * im.height)
    a = np.asarray(im.crop((0, lo, im.width, hi)), dtype=float)
    return a * np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))


def _parabolic(y0: float, y1: float, y2: float) -> float:
    """Sub-pixel peak offset from three samples around the maximum."""
    d = y0 - 2 * y1 + y2
    return 0.0 if d == 0 else 0.5 * (y0 - y2) / d


def shift_px(a: np.ndarray, b: np.ndarray, sign: int = 0) -> tuple[float, float, float]:
    """Phase correlation. Returns (dx, dy, peak) where dx > 0 means the scene
    slid left between a and b, i.e. the camera panned Right.

    `sign` restricts the peak search to one direction of pan. A sweep only ever
    turns one way, so a step that comes back negative is a false peak — over a
    repetitive treeline the correlation does pick one. Re-running that step with
    the sweep's own direction recovers it.
    """
    fa, fb = np.fft.rfft2(a), np.fft.rfft2(b)
    r = fa * np.conj(fb)
    corr = np.fft.irfft2(r / (np.abs(r) + 1e-12), s=a.shape)
    h, w = corr.shape
    search = corr
    if sign:
        lags = np.arange(w)
        lags = np.where(lags > w / 2, lags - w, lags)
        search = np.where(lags * sign >= 0, corr, -np.inf)   # keep lag 0: a dropped step
    iy, ix = np.unravel_index(np.argmax(search), search.shape)
    dx = ix + _parabolic(corr[iy, (ix - 1) % w], corr[iy, ix], corr[iy, (ix + 1) % w])
    dy = iy + _parabolic(corr[(iy - 1) % h, ix], corr[iy, ix], corr[(iy + 1) % h, ix])
    if dx > w / 2:
        dx -= w
    if dy > h / 2:
        dy -= h
    return dx, dy, float(corr[iy, ix])


class Step(NamedTuple):
    pose_a: int
    pose_b: int
    dx: float
    dy: float
    peak: float
    repaired: bool = False      # re-measured against the sweep direction


def measure_steps(folder, band: tuple[float, float] = BAND) -> tuple[list[Step], int]:
    """Shift of every consecutive pose pair in `folder`. Returns (steps, image_w)."""
    poses = latest_per_pose(folder)
    ids = list(poses)
    if len(ids) < 3:
        raise ValueError(f"need at least 3 poses, found {len(ids)}")
    greys = {i: _grey(poses[i], band) for i in ids}
    image_w = Image.open(poses[ids[0]]).width
    steps = []
    for a, b in zip(ids, ids[1:]):
        dx, dy, peak = shift_px(greys[a], greys[b])
        steps.append(Step(a, b, dx, dy, peak))

    # a sweep turns one way only: a step that disagrees with the majority is a
    # false correlation peak, not the camera reversing. Measure it again, this
    # time looking only in the direction the sweep actually went.
    direction = 1 if sorted(s.dx for s in steps)[len(steps) // 2] > 0 else -1
    for i, s in enumerate(steps):
        if s.dx * direction < -STILL_PX:
            dx, dy, peak = shift_px(greys[s.pose_a], greys[s.pose_b], direction)
            steps[i] = Step(s.pose_a, s.pose_b, dx, dy, peak, repaired=True)
    return steps, image_w


def closure_shift(folder, pose_a: int, pose_b: int,
                  band: tuple[float, float] = BAND) -> tuple[float, float]:
    """(shift, correlation peak) between the two ends of the loop, which overlap
    once the sweep has gone right round. A weak peak means they do not actually
    overlap — the shift is then meaningless."""
    poses = latest_per_pose(folder)
    dx, _, peak = shift_px(_grey(poses[pose_a], band), _grey(poses[pose_b], band))
    return dx, peak


# ── FOV from loop closure ─────────────────────────────────────────────────────

def solve_fov(dx_steps: list[float], dx_close: float, image_w: int,
              lo: float = 20.0, hi: float = 120.0, tol: float = 1e-9) -> float | None:
    """FOV making the measured steps add up to exactly one turn.

    Going from pose p0 to pose p0+n covers a full turn plus whatever pose p0+n
    still overlaps p0 by (`dx_close`, measured directly between those two frames):

        sum(angle(dx_i, fov)) - angle(dx_close, fov) = +/- 360

    The sign follows the sweep direction, so a Left sweep fits the same way.

    One unknown, no clicks, no datasheet value. Returns None when no FOV in
    [lo, hi] satisfies it — which means the loop pose is wrong, or a step is so
    badly broken that correlation locked onto the wrong peak.
    """
    turn = math.copysign(360.0, sum(dx_steps))

    def residual(fov: float) -> float:
        total = sum(shift_to_angle(dx, image_w, fov) for dx in dx_steps)
        return total - shift_to_angle(dx_close, image_w, fov) - turn

    f_lo, f_hi = residual(lo), residual(hi)
    if f_lo * f_hi > 0:
        return None
    # residual is monotonic in fov (checked in demo()), plain bisection is enough
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if residual(mid) * f_lo > 0:
            lo, f_lo = mid, residual(mid)
        else:
            hi = mid
    return (lo + hi) / 2


def suggest_loop_pose(steps: list["Step"], image_w: int, peak_of,
                      fov_guess: float = 54.2, min_span: float = 180.0):
    """Pose that closes the loop, and its correlation peak with the first pose.

    Among the poses at least half a turn away, the one whose frame still
    correlates best with the first: the strongest peak is the largest overlap,
    which is the pose closest to a full turn. Chosen on the peak rather than on a
    cumulative angle, because the cumulative angle needs a FOV — the very thing
    being fitted. A pose that does *not* overlap still produces a shift, and the
    solver then fits a plausible-looking FOV to noise.
    """
    cum, best = 0.0, None
    for s in steps:
        cum += shift_to_angle(s.dx, image_w, fov_guess)
        if abs(cum) >= min_span:      # abs: a Left sweep accumulates negative
            peak = peak_of(s.pose_b)
            if best is None or peak > best[1]:
                best = (s.pose_b, peak)
    return best


# ── azimuths ──────────────────────────────────────────────────────────────────

def pose_azimuths(steps: list[Step], image_w: int, fov: float,
                  anchor_pose: int, anchor_az: float) -> dict[int, float]:
    """Cumulative sum of the measured angles, anchored so `anchor_pose` centre
    points at `anchor_az`."""
    az = {steps[0].pose_a: 0.0}
    for s in steps:
        az[s.pose_b] = az[s.pose_a] + shift_to_angle(s.dx, image_w, fov)
    offset = anchor_az - az[anchor_pose]
    return {p: (a + offset) % 360.0 for p, a in az.items()}


class Landmark(NamedTuple):
    pose: int
    x: float           # native pixel column where it was clicked
    az: float          # its compass azimuth, read on a map or surveyed
    y: float = 0.0     # only to draw the marker back


# A landmark disagreeing with the others by more than this is misread on the
# map, or clicked on the wrong thing: the sweep itself closes to 0.3 degrees.
RESIDUAL_DEG = 0.5


def anchor_from_landmarks(steps: list[Step], image_w: int, fov: float,
                          landmarks: list[Landmark]) -> tuple[dict[int, float], list[float]]:
    """Azimuth of every pose from one or more landmarks of known azimuth.

    Each landmark votes for the one global offset of the sweep. The median vote
    wins, so a landmark misread on the map shows up as its own residual instead
    of dragging every pose. Returns (azimuths, residual of each landmark)."""
    az0 = pose_azimuths(steps, image_w, fov, steps[0].pose_a, 0.0)
    votes = [(lm.az - pixel_to_angle(lm.x, image_w, fov) - az0[lm.pose]) % 360.0
             for lm in landmarks]
    votes = [votes[0] + (v - votes[0] + 180.0) % 360.0 - 180.0 for v in votes]  # unwrap
    offset = float(np.median(votes))
    return {p: (a + offset) % 360.0 for p, a in az0.items()}, [v - offset for v in votes]


# ── self-check ────────────────────────────────────────────────────────────────

def demo() -> None:
    rng = np.random.default_rng(0)

    # ── phase correlation: sign convention and sub-pixel accuracy ────────────
    scene = rng.random((64, 512))
    a = scene[:, 100:400]
    b = scene[:, 120:420]          # b shows the scene 20 px further right,
    dx, dy, _ = shift_px(a * 1.0, b * 1.0)   # i.e. the scene slid 20 px left
    assert abs(dx - 20) < 0.5, f"dx {dx} != 20 (camera panned Right)"
    assert abs(dy) < 0.5, dy
    dx_back, _, _ = shift_px(b * 1.0, a * 1.0)
    assert abs(dx_back + 20) < 0.5, f"panning Left must be negative, got {dx_back}"
    # the restricted search must stay on its side of zero even when the real
    # peak is on the other one
    wrong, _, _ = shift_px(a * 1.0, b * 1.0, sign=-1)
    assert wrong < 0, wrong
    right, _, _ = shift_px(a * 1.0, b * 1.0, sign=1)
    assert abs(right - 20) < 0.5, right
    # a dropped step is 0 +/- noise: the restricted search must keep lag 0
    still, _, _ = shift_px(a * 1.0, a + 0.05 * rng.random(a.shape), sign=1)
    assert abs(still) < 0.5, f"lag 0 must survive the restriction, got {still}"

    # ── geometry ─────────────────────────────────────────────────────────────
    W = 1280
    assert abs(shift_to_angle(0, W, 54.2)) < 1e-12
    assert shift_to_angle(500, W, 54.2) > 0
    # a full-frame shift is one FOV only in the linear model; the tangent model
    # says less, and that gap is the whole point of not using the linear one
    assert shift_to_angle(W, W, 54.2) < 54.2

    # ── FOV solver against a camera whose truth we know ──────────────────────
    TRUE_FOV, TRUE_STEP = 51.3, 12.37       # neither 54.2 nor the commanded 12.5
    f = focal_px(W, TRUE_FOV)
    n = 29                                   # 29 * 12.37 = 358.7deg, just short
    thetas = [TRUE_STEP] * n
    thetas[7] = 0.0                          # one step silently dropped
    thetas[12] = TRUE_STEP * 1.4             # one long step
    total = sum(thetas)
    dx_steps = [f * math.tan(math.radians(t)) for t in thetas]
    # what pose p0+n still overlaps p0 by, given the sweep went `total` degrees
    dx_close = f * math.tan(math.radians(total - 360.0))

    got = solve_fov(dx_steps, dx_close, W)
    assert got is not None and abs(got - TRUE_FOV) < 1e-6, got

    # the datasheet FOV would have mis-stated the span by a real margin
    naive = sum(shift_to_angle(dx, W, 54.2) for dx in dx_steps)
    assert abs(naive - total) > 1.0, naive

    # bisection needs a monotonic residual over the bracket
    res = [sum(shift_to_angle(dx, W, fov) for dx in dx_steps)
           - shift_to_angle(dx_close, W, fov) - 360.0 for fov in range(20, 121)]
    d = [y - x for x, y in zip(res, res[1:])]
    assert all(v > 0 for v in d) or all(v < 0 for v in d), "residual must be monotonic"

    assert solve_fov(dx_steps, dx_close, W, lo=80.0, hi=120.0) is None

    # a Left sweep is the same measurement mirrored
    left = solve_fov([-dx for dx in dx_steps], -dx_close, W)
    assert left is not None and abs(left - TRUE_FOV) < 1e-6, left

    # ── azimuths: cumulative, and the dropped step stays local ───────────────
    steps = [Step(20 + i, 21 + i, dx, 0.0, 1.0) for i, dx in enumerate(dx_steps)]
    az = pose_azimuths(steps, W, TRUE_FOV, anchor_pose=20, anchor_az=100.0)
    assert abs(az[20] - 100.0) < 1e-9
    assert abs(az[21] - (100.0 + TRUE_STEP)) < 1e-6
    assert abs(az[28] - az[27]) < 1e-9, "the dropped step must show as no rotation"
    assert abs(az[20 + n] - (100.0 + total) % 360.0) < 1e-6

    # loop pose: half a turn away at least, then the strongest overlap wins
    fake_peaks = {p: 0.01 for p in range(20, 20 + n + 1)}
    fake_peaks[48], fake_peaks[49] = 0.05, 0.16
    got_loop = suggest_loop_pose(steps, W, fake_peaks.get, TRUE_FOV)
    assert got_loop == (49, 0.16), got_loop
    mirrored = [s._replace(dx=-s.dx) for s in steps]
    assert suggest_loop_pose(mirrored, W, fake_peaks.get, TRUE_FOV) == (49, 0.16)

    # ── landmarks ────────────────────────────────────────────────────────────
    def seen_at(landmark_az: float, pose: int) -> float:
        """Pixel column where a landmark lands in a pose, on the true camera."""
        return W / 2 + f * math.tan(math.radians(landmark_az - az[pose]))

    one = [Landmark(20, seen_at(90.0, 20), 90.0)]
    az1, res = anchor_from_landmarks(steps, W, TRUE_FOV, one)
    assert res == [0.0] and all(abs(az1[p] - az[p]) < 1e-6 for p in az), "one landmark = the anchor"
    # a second one on the other side of the sweep agrees, a misread one stands out
    three = one + [Landmark(35, seen_at(275.0, 35), 275.0), Landmark(45, seen_at(30.0, 45), 33.0)]
    az3, res = anchor_from_landmarks(steps, W, TRUE_FOV, three)
    assert abs(res[0]) < 1e-6 and abs(res[1]) < 1e-6 and abs(res[2] - 3.0) < 1e-6, res
    assert all(abs(az3[p] - az[p]) < 1e-6 for p in az), "the median ignores the bad one"
    # wrap-around: a landmark just past north votes with the others
    wrap = [Landmark(20, seen_at(359.5, 20), 359.5), Landmark(21, seen_at(0.5, 21), 0.5)]
    _, res = anchor_from_landmarks(steps, W, TRUE_FOV, wrap)
    assert max(abs(r) for r in res) < 1e-6, res

    _demo_end_to_end()
    print("pose_azimuth: all checks passed")


def _demo_end_to_end() -> None:
    """The whole pipeline on rendered frames — the only check that exercises the
    correlation itself, and the rectilinear-vs-translation bias it carries."""
    import tempfile

    W, H, FOV, STEP, WP = 640, 360, 51.3, 12.37, 10000
    rng = np.random.default_rng(1)
    pano = rng.random((H, WP))
    for _ in range(3):                      # pure noise correlates too easily
        pano = (pano + np.roll(pano, 1, axis=1) + np.roll(pano, 1, axis=0)) / 3
    pano = (pano - pano.min()) / (pano.max() - pano.min()) * 255

    f = focal_px(W, FOV)
    col_ang = np.degrees(np.arctan((np.arange(W) - W / 2) / f))

    def render(az: float) -> Image.Image:
        cols = np.round((az + col_ang) / 360.0 * WP).astype(int) % WP
        return Image.fromarray(pano[:, cols].astype(np.uint8)).convert("RGB")

    thetas = [STEP] * 29
    thetas[7] = 0.0                         # a step the camera silently dropped
    thetas[12] = STEP * 1.4                 # and one it overshot
    az_true, a = [100.0], 100.0
    for t in thetas:
        a += t
        az_true.append(a)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for i, az in enumerate(az_true):
            render(az).save(d / f"pose_{20 + i:02d}_20260917120000.jpg", quality=95)

        steps, image_w = measure_steps(d)
        assert image_w == W and len(steps) == len(thetas)
        assert not any(s.repaired for s in steps), "a clean sweep needs no repair"

        peaks = {}

        def peak_of(pose: int) -> float:
            if pose not in peaks:
                peaks[pose] = closure_shift(d, 20, pose)[1]
            return peaks[pose]

        loop, peak = suggest_loop_pose(steps, image_w, peak_of)
        assert loop == 49, f"loop pose {loop}: the last one is the closest to a turn"
        # a pose that does not overlap correlates an order of magnitude worse
        assert peak > 3 * peak_of(45), (peak, peak_of(45))

        dx_close, _ = closure_shift(d, 20, loop)
        used = [s for s in steps if s.pose_a < loop]
        fov = solve_fov([s.dx for s in used], dx_close, image_w)

    assert fov is not None and abs(fov - FOV) < 1.0, f"fov {fov} != {FOV}"

    az = pose_azimuths(steps, image_w, fov, 20, 100.0)
    errs = [abs((az[20 + i] - t + 180) % 360 - 180) for i, t in enumerate(az_true)]
    assert max(errs) < 0.3, f"worst azimuth error {max(errs):.3f}deg"

    measured = [shift_to_angle(s.dx, image_w, fov) for s in steps]
    assert abs(measured[7]) < 0.05, "a dropped step must read as no rotation"
    assert abs(measured[12] - thetas[12]) < 0.3, measured[12]
    # and it stays local: the poses after it are not shifted by it
    assert abs((az[29] - az[28]) - STEP) < 0.3


if __name__ == "__main__":
    demo()
