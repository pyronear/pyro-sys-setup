"""
Page 1 — Pose calibration: one azimuth per pose.

Works offline on a capture folder, no camera needed.

  1. measure every step by phase correlation (the commanded angle is not the
     angle the camera turned)
  2. fit the real FOV by loop closure — the sweep overshoots 360°
  3. click one landmark of known azimuth to anchor the whole sweep
"""

import csv
from pathlib import Path
import sys

import streamlit as st
from PIL import Image, ImageDraw

from streamlit_image_coordinates import streamlit_image_coordinates

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture_poses import CAPTURES_DIR
from pixel_shift import latest_per_pose, to_native
from pose_azimuth import (BAND, STILL_PX, anchor_from_click, closure_shift, measure_steps,
                          pose_azimuths, shift_to_angle, solve_fov, suggest_loop_pose)

WEAK_RATIO = 0.4          # peak this far under the median: the pair barely matched

st.set_page_config(page_title="Pose calibration", layout="wide")
st.title("1 · Pose calibration")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")

# ── pick the capture folder ───────────────────────────────────────────────────
cam_dirs = sorted(p for p in (CAPTURES_DIR / pi_ip).glob("*/images") if p.is_dir())
if not cam_dirs:
    st.error(f"No captures under `{CAPTURES_DIR / pi_ip}` — run page 0 first.")
    st.stop()

img_dir = Path(st.selectbox("Camera", cam_dirs, format_func=lambda p: p.parent.name))
cam_dir = img_dir.parent
poses = latest_per_pose(img_dir)
st.caption(f"{len(poses)} poses — {min(poses)} … {max(poses)}")

# keep the newest mtime in the cache keys so measurements never outlive the
# images they were made from
stamp = max(p.stat().st_mtime for p in poses.values())

# ── 1 · measure every step ────────────────────────────────────────────────────
st.subheader("1 · Measured steps")


band = st.slider(
    "Rows used for correlation (fraction of image height)", 0.0, 1.0, BAND, 0.01,
    help="Keep the ground. The sky is worse than useless — the clouds move "
         "between two captures — and the bottom of the frame often holds the "
         "mast the camera sits on, identical in every pose, which drags the "
         "correlation onto a false zero shift. Depends on the tilt: adjust per camera.")


@st.cache_data(show_spinner="Correlating consecutive poses…")
def _steps(folder: str, n_files: int, band: tuple, stamp: float):
    return measure_steps(Path(folder), band)


if st.button("📐 Measure steps", type="primary"):
    st.cache_data.clear()

try:
    steps, image_w = _steps(str(img_dir), len(poses), band, stamp)
except Exception as e:
    st.error(f"Measurement failed: {e}")
    st.stop()

pose_ids = [steps[0].pose_a] + [s.pose_b for s in steps]
first_pose = pose_ids[0]


@st.cache_data(show_spinner=False)
def _closure(folder: str, pose_a: int, pose_b: int, band: tuple, stamp: float):
    return closure_shift(Path(folder), pose_a, pose_b, band)


with st.spinner("Looking for the loop-closing pose…"):
    guess = suggest_loop_pose(steps, image_w,
                              lambda p: _closure(str(img_dir), first_pose, p, band, stamp)[1])
if guess is None:
    st.error("The sweep never got half a turn round — nothing to close the loop on.")
    st.stop()
guess_pose, guess_peak = guess

c1, c2 = st.columns(2)
loop_pose = c1.selectbox(
    "Loop-closing pose (comes back onto the first one)", pose_ids[1:],
    index=pose_ids[1:].index(guess_pose),
    help="The pose that overlaps the first one again after a full turn. That "
         "overlap is what fits the FOV. Picked as the strongest correlation "
         "with the first pose.",
)


def fit(loop_p: int):
    """(fov, steps used) for a given loop-closing pose."""
    used = [s for s in steps if s.pose_a < loop_p]
    dx_close, _ = _closure(str(img_dir), first_pose, loop_p, band, stamp)
    return solve_fov([s.dx for s in used], dx_close, image_w), used


med_peak = sorted(s.peak for s in steps)[len(steps) // 2]
loop_peak = _closure(str(img_dir), first_pose, int(loop_pose), band, stamp)[1]
if loop_peak < 3 * med_peak:
    st.warning(f"Pose {loop_pose} barely correlates with pose {first_pose} "
               f"(peak {loop_peak:.3f} against {med_peak:.3f} for a plain step) — "
               "they probably do not overlap, and the fit below would then be "
               f"noise. Best candidate was pose {guess_pose} (peak {guess_peak:.3f}).")

fov, used = fit(int(loop_pose))
if fov is None:
    st.error("No FOV in 20–120° closes the loop — wrong loop pose, or a step "
             "correlation locked onto the wrong peak. Check the table below.")
    st.stop()

# neighbouring loop poses are a near-independent fit: they must agree
spread, alt_fovs = [], []
for alt in (int(loop_pose) - 1, int(loop_pose) + 1):
    if alt in pose_ids and alt > first_pose:
        alt_fov, _ = fit(alt)
        if alt_fov:
            alt_fovs.append(alt_fov)
            spread.append(f"{alt}: {alt_fov:.2f}°")

# the fit only spans the loop, but every step is shown: a bad one past the
# loop pose still lands in the exported azimuths
angles = [shift_to_angle(s.dx, image_w, fov) for s in steps]
in_fit = [s.pose_a < int(loop_pose) for s in steps]
fit_angles = [a for a, keep in zip(angles, in_fit) if keep]
c2.metric("Fitted FOV", f"{fov:.2f}°",
          help="Measured on this camera at this zoom — never the datasheet value.")
st.caption(f"Span {first_pose}→{loop_pose}: **{sum(fit_angles):.2f}°** over {len(used)} steps · "
           f"mean step **{sum(fit_angles) / len(used):.2f}°** · "
           + (f"same fit from neighbouring loop poses — {', '.join(spread)}"
              if spread else "no neighbouring loop pose to cross-check"))

# one corroborating neighbour is enough: the other one may simply not overlap
if alt_fovs and min(abs(f - fov) for f in alt_fovs) > 1.0:
    st.warning("No neighbouring loop pose corroborates this FOV (all differ by "
               "more than 1°) — the closure pair is probably matching the wrong "
               "thing. Try another loop pose, or move the band onto the ground.")

mean_step = sum(fit_angles) / len(fit_angles)      # negative on a Left sweep
rows = [{"pose": f"{s.pose_a}→{s.pose_b}", "in fit": keep,
         "dx (px)": round(s.dx, 1),
         "dy (px)": round(s.dy, 1), "angle (°)": round(a, 2),
         "peak": round(s.peak, 3),
         "flag": ("🛑 no rotation" if abs(s.dx) < STILL_PX else
                  "↩ re-measured" if s.repaired else
                  "⚠ weak match" if s.peak < WEAK_RATIO * med_peak else
                  "⚠ outlier" if abs(a - mean_step) > 0.3 * abs(mean_step) else "")}
        for s, a, keep in zip(steps, angles, in_fit)]
st.dataframe(rows, width="stretch", hide_index=True)

still = [r["pose"] for r in rows if r["flag"].startswith("🛑")]
if still:
    st.error(
        f"Zero rotation measured on {', '.join(still)}. **Open those two frames "
        "and check by eye.** The camera does silently drop a PTZ command, and a "
        "real dropped step is handled correctly — but two frames sharing a fixed "
        "foreground (the mast, a roof) also correlate at zero shift. If the view "
        "did change, move the band above onto the ground and measure again.")
elif any(s.repaired for s in steps):
    st.info("A step came back turning against the sweep, which the camera cannot "
            "do, so it was measured again looking only the way the sweep goes. "
            "Cross-check it: the poses after it all shift with it.")
elif any(r["flag"] for r in rows):
    st.warning("Flagged steps are kept as measured — a step that really is short "
               "or long stays local. Re-run the sweep only if an image is unusable.")

# ── 2 · anchor ────────────────────────────────────────────────────────────────
st.subheader("2 · Azimuth anchor")
st.caption("Click a landmark whose compass azimuth you know (map, survey), then "
           "enter that azimuth.")

idx_key = f"anchor_idx_{cam_dir.name}"
idx = min(st.session_state.get(idx_key, 0), len(pose_ids) - 1)

a1, a2, a3 = st.columns([1, 1, 2])
with a1:
    st.caption("Pose — arrow through the sweep to find your landmark")
    prev_col, show_col, next_col = st.columns([1, 2, 1])
    if prev_col.button("◀", disabled=idx == 0, width="stretch"):
        st.session_state[idx_key] = idx - 1
        st.rerun()
    show_col.subheader(pose_ids[idx])
    if next_col.button("▶", disabled=idx == len(pose_ids) - 1, width="stretch"):
        st.session_state[idx_key] = idx + 1
        st.rerun()
anchor_pose = pose_ids[idx]
landmark_az = a2.number_input("Landmark azimuth (°)", 0.0, 360.0, 180.0, 0.1)
disp_w = a3.slider("Display width (px)", 400, 1600, 900, 50,
                   help="Display only — clicks are rescaled to native pixels.")

key = f"anchor_{cam_dir.name}_{anchor_pose}"
img = Image.open(poses[anchor_pose])
shown = img
if st.session_state.get(key):
    x, y = st.session_state[key]
    shown = img.copy()
    d = ImageDraw.Draw(shown)
    d.line([(x - 16, y), (x + 16, y)], fill=(255, 80, 80), width=3)
    d.line([(x, y - 16), (x, y + 16)], fill=(255, 80, 80), width=3)
    d.ellipse([(x - 16, y - 16), (x + 16, y + 16)], outline=(255, 80, 80), width=2)

click = streamlit_image_coordinates(shown, width=disp_w, key=f"click_{key}")
if click:
    native = to_native(click, img.width, img.height)
    if st.session_state.get(key) != native:
        st.session_state[key] = native
        st.rerun()

if not st.session_state.get(key):
    st.info("Click the landmark in the image above.")
    st.stop()

click_x = st.session_state[key][0]
anchor_az = anchor_from_click(click_x, img.width, fov, landmark_az)
st.caption(f"Landmark at x={click_x:.0f}/{img.width} → centre of pose "
           f"{anchor_pose} points at **{anchor_az:.2f}°**")

# ── 3 · result ────────────────────────────────────────────────────────────────
st.subheader("3 · Pose azimuths")

az = pose_azimuths(steps, image_w, fov, int(anchor_pose), anchor_az)
gap = {s.pose_a: fov - abs(shift_to_angle(s.dx, image_w, fov)) for s in steps}
out = [{"pose": p, "azimuth (°)": round(a, 2),
        "overlap with next (°)": round(gap[p], 1) if p in gap else None,
        "blind gap": "⚠" if p in gap and gap[p] < 0 else ""}
       for p, a in az.items()]
st.dataframe(out, width="stretch", hide_index=True)

blind = [r["pose"] for r in out if r["blind gap"]]
if blind:
    st.error(f"Blind sector after pose(s) {blind} — a step turned more than the FOV.")

csv_path = cam_dir / "calibration.csv"
if st.button(f"💾 Save {csv_path.name}", type="primary"):
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pose", "az_center", "fov_deg", "image_w", "anchor_pose", "anchor_az"])
        for p, a in az.items():
            w.writerow([p, f"{a:.3f}", f"{fov:.3f}", image_w, anchor_pose, f"{anchor_az:.3f}"])
    st.success(f"Saved {csv_path}")
