"""
Page 2 — Azimuth calibration.

Workflow:
  1. Click the same object on the panorama start-pose  → overlap_start (px_left)
  2. Click the same object on the panorama end-pose    → overlap_end   (px_right)
     → px_per_deg = (px_right - px_left) / 360
  3. Click any landmark with a known azimuth           → az_ref (px_ref + az_ref°)
     → anchors the absolute direction

Azimuths for all poses are derived and saved to calibration.csv.
"""

from pathlib import Path
import glob
import json
import re
import sys

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── constants ─────────────────────────────────────────────────────────────────
CAPTURES_DIR       = Path(__file__).parent.parent / "captures"
PANO_DISPLAY_WIDTH = 1400
MIN_INLIERS        = 8
RANSAC_THRESH      = 3.0
DEFAULT_FOV        = 54.2

SLOTS = ["overlap_start", "overlap_end", "az_ref"]
SLOT_LABELS = {
    "overlap_start": "① Overlap — start",
    "overlap_end":   "② Overlap — end",
    "az_ref":        "③ Azimuth reference",
}
SLOT_COLORS = {
    "overlap_start": (50, 200, 50),
    "overlap_end":   (255, 165, 0),
    "az_ref":        (255, 50, 50),
}

st.set_page_config(page_title="Calibration", layout="wide")
st.title("2 · Azimuth calibration")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")
st.sidebar.markdown(f"**Pi IP:** `{pi_ip}`")

# ── helpers ───────────────────────────────────────────────────────────────────

def pose_num(path: Path) -> int:
    m = re.search(r"pose_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def load_bgr(path: Path) -> np.ndarray:
    im = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(str(path))
    return im


def match_knn(desc1, desc2):
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 100})
    matches = matcher.knnMatch(desc1, desc2, k=2)
    return [m for m, n in matches if m.distance < 0.75 * n.distance]


def find_homography(kp1, kp2, matches):
    if len(matches) < 12:
        return None, 0, None
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_THRESH)
    if H is None or mask is None:
        return None, 0, None
    inliers = mask.ravel().astype(bool)
    proj = cv2.perspectiveTransform(src[inliers], H)
    rms = float(np.sqrt((np.linalg.norm(proj - dst[inliers], axis=2) ** 2).mean()))
    return H, int(inliers.sum()), rms


def project_point(x, y, H):
    out = cv2.perspectiveTransform(np.float32([[[x, y]]]), H)[0, 0]
    return float(out[0]), float(out[1])


def az_from_x(x, ref_az, ref_px, px_per_deg):
    return (ref_az + (x - ref_px) / px_per_deg) % 360.0


def draw_crosshair(img: Image.Image, points: list[tuple[int, int, tuple]]) -> Image.Image:
    """Draw one crosshair per (x, y, color) tuple."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    r = 16
    for x, y, color in points:
        draw.line([(x - r, y), (x + r, y)], fill=color, width=3)
        draw.line([(x, y - r), (x, y + r)], fill=color, width=3)
        draw.ellipse([(x - r, y - r), (x + r, y + r)], outline=color, width=2)
    return out


def _draw_marker(draw: ImageDraw.ImageDraw, x: int, y: int, color: tuple) -> None:
    r = 14
    draw.line([(x - r, y), (x + r, y)], fill=color, width=3)
    draw.line([(x, y - r), (x, y + r)], fill=color, width=3)
    draw.ellipse([(x - r, y - r), (x + r, y + r)], outline=color, width=2)


def annotate_panorama(pano: Image.Image, scale: float, cx_list: list[float],
                      slot_pano_x: dict) -> Image.Image:
    img = pano.copy()
    draw = ImageDraw.Draw(img)
    h = img.height
    for cx in cx_list:
        x = int(cx * scale)
        draw.line([(x, 0), (x, h)], fill=(100, 149, 237), width=2)
    for slot, color in SLOT_COLORS.items():
        info = slot_pano_x.get(slot)
        if info is not None:
            _draw_marker(draw, int(info["pano_x"] * scale), h // 2, color)
    return img


def load_pose_offsets(offsets_path: Path, image_paths: list[str]):
    """Return (DataFrame, px_per_deg_from_phase_corr | None)."""
    if not offsets_path.exists():
        return None, None

    data = json.loads(offsets_path.read_text())
    if "poses" in data:
        poses = data["poses"]
        px_per_deg = data["effective_shift_px"] / data["step_deg"]
    else:
        poses = data
        px_per_deg = None

    img_w = load_bgr(Path(image_paths[0])).shape[1]
    rows = []
    for p_str in image_paths:
        p = Path(p_str)
        if p.name in poses:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=poses[p.name],
                             inliers=None, rms=None, error=None, img_w=img_w))
        else:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=None,
                             inliers=0, rms=None, error="not in offsets", img_w=img_w))

    return pd.DataFrame(rows).sort_values("pose").reset_index(drop=True), px_per_deg


@st.cache_data(show_spinner="Matching poses against panorama…")
def compute_pose_positions_sift(pano_path: str, image_paths: list[str]):
    pano = load_bgr(Path(pano_path))
    extractor = cv2.SIFT_create(nfeatures=12000)
    kp_pano, des_pano = extractor.detectAndCompute(pano, None)
    img_w = load_bgr(Path(image_paths[0])).shape[1]

    rows, Hs = [], {}
    for p_str in image_paths:
        p = Path(p_str)
        src = load_bgr(p)
        kp, des = extractor.detectAndCompute(src, None)
        if des is None or len(kp) < 8:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=None, cy=None,
                             inliers=0, rms=None, error="few features", img_w=img_w))
            continue
        good = match_knn(des, des_pano)
        H, n_in, rms = find_homography(kp, kp_pano, good)
        if H is None or n_in < MIN_INLIERS:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=None, cy=None,
                             inliers=n_in, rms=None, error=f"{n_in} inliers", img_w=img_w))
            continue
        h_img, w_img = src.shape[:2]
        cx, cy = project_point(w_img * 0.5, h_img * 0.5, H)
        rows.append(dict(name=p.name, pose=pose_num(p), cx=cx, cy=cy,
                         inliers=n_in, rms=rms, error=None, img_w=img_w))
        Hs[p.name] = H

    df = pd.DataFrame(rows).sort_values("pose").reset_index(drop=True)
    return df, Hs


# ── sidebar: camera selector ──────────────────────────────────────────────────
base = CAPTURES_DIR / pi_ip
cam_dirs = sorted(
    Path(c).name for c in glob.glob(str(base / "*"))
    if (Path(c) / "images").is_dir() and (Path(c) / "panorama_full.jpg").exists()
)
if not cam_dirs:
    st.warning(f"No cameras with a panorama found under `{base}`. Run the Capture page first.")
    st.stop()

with st.sidebar:
    cam = st.selectbox("Camera", cam_dirs)
    fov_deg = st.number_input("Camera FOV (°)", value=DEFAULT_FOV, step=0.1, format="%.1f")

folder      = base / cam / "images"
pano_path   = base / cam / "panorama_full.jpg"
image_paths = sorted(
    [str(p) for p in folder.glob("*.jpg") if not p.name.startswith("panorama")],
    key=lambda s: pose_num(Path(s)),
)
if not image_paths:
    st.error(f"No pose images in {folder}")
    st.stop()

# ── session state ─────────────────────────────────────────────────────────────
# Each slot: None | {"pose": str, "img_x": int, "img_y": int, "pano_x": float}
for key in SLOTS:
    if key not in st.session_state:
        st.session_state[key] = None
for key, default in [("pose_idx", 0), ("click_mode", "overlap_start")]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── compute matches ───────────────────────────────────────────────────────────
offsets_path            = base / cam / "pose_offsets.json"
df_offsets, px_per_deg_phase = load_pose_offsets(offsets_path, image_paths)

# SIFT is only used for the panorama overview cx lines when pose_offsets.json is absent.
# Click-to-panorama mapping uses offset-based projection (immune to >360° scene repetition).
if df_offsets is None:
    df_sift, _ = compute_pose_positions_sift(str(pano_path), image_paths)
    df = df_sift
else:
    df = df_offsets
valid = df[df["cx"].notna()]

# ── step 1: browse & click ────────────────────────────────────────────────────
st.header("1 · Collect calibration points")
st.caption(
    "① Click the **same object** on a pose near the **start** of the sweep.  "
    "② Click it again on a pose near the **end** (>360° overlap).  "
    "③ Click any **landmark with a known azimuth**."
)

# Click-mode selector
mode = st.radio(
    "Placing:",
    SLOTS,
    format_func=lambda s: SLOT_LABELS[s],
    index=SLOTS.index(st.session_state.click_mode),
    horizontal=True,
)
st.session_state.click_mode = mode

# Pose browser
total = len(image_paths)
idx   = st.session_state.pose_idx

col_prev, col_label, col_next = st.columns([1, 5, 1])
with col_prev:
    if st.button("← Prev", width="stretch") and idx > 0:
        st.session_state.pose_idx -= 1
        st.rerun()
with col_next:
    if st.button("Next →", width="stretch") and idx < total - 1:
        st.session_state.pose_idx += 1
        st.rerun()
with col_label:
    st.markdown(f"**{Path(image_paths[idx]).name}** &nbsp;({idx + 1}/{total})")

current_name = Path(image_paths[idx]).name
current_row  = df[df["name"] == current_name]
has_cx       = not current_row.empty and pd.notna(current_row.iloc[0]["cx"])

col_img, col_slots = st.columns([3, 1])
with col_img:
    pose_pil = Image.open(image_paths[idx])
    img_w    = pose_pil.width

    # Draw crosshairs for any slot already clicked on this pose
    crosshairs = [
        (info["img_x"], info["img_y"], SLOT_COLORS[slot])
        for slot in SLOTS
        if (info := st.session_state[slot]) is not None and info["pose"] == current_name
    ]
    annotated = draw_crosshair(pose_pil, crosshairs) if crosshairs else pose_pil

    if has_cx:
        cx_pose = float(current_row.iloc[0]["cx"])
        click = streamlit_image_coordinates(annotated, key=f"click_{current_name}_{mode}")
        if click:
            current_slot = st.session_state[mode]
            if current_slot is None or click["x"] != current_slot["img_x"] or click["y"] != current_slot["img_y"]:
                # Offset-based projection: panorama_x = pose_center_x + (click_x - img_w/2)
                # This is immune to >360° scene repetition that breaks SIFT homography.
                pano_x = cx_pose + (click["x"] - img_w / 2)
                st.session_state[mode] = {
                    "pose":   current_name,
                    "img_x":  click["x"],
                    "img_y":  click["y"],
                    "pano_x": pano_x,
                }
                # Advance mode automatically
                next_idx = SLOTS.index(mode) + 1
                if next_idx < len(SLOTS):
                    st.session_state.click_mode = SLOTS[next_idx]
                st.rerun()
    else:
        st.image(annotated, width="stretch")
        reason = current_row.iloc[0]["error"] if not current_row.empty else "unknown"
        st.warning(f"Pose position unknown ({reason}) — pick another pose.")

with col_slots:
    st.markdown("**Calibration points**")
    for slot in SLOTS:
        info = st.session_state[slot]
        color_hex = "#{:02x}{:02x}{:02x}".format(*SLOT_COLORS[slot])
        label = SLOT_LABELS[slot]
        if info is not None:
            st.markdown(
                f":{color_hex}[**{label}**]  \n"
                f"pose: `{info['pose']}`  \n"
                f"pano x: `{info['pano_x']:.0f}`"
            )
            if st.button("Clear", key=f"clear_{slot}"):
                st.session_state[slot] = None
                st.rerun()
        else:
            st.markdown(f"*{label}*  \n—")

    if st.session_state["az_ref"] is not None:
        st.divider()
        ref_az = st.number_input("Azimuth of ③ (°)", 0.0, 360.0, value=0.0, step=0.1, format="%.1f")
    else:
        ref_az = 0.0

# ── panorama overview ─────────────────────────────────────────────────────────
with st.expander("Panorama overview"):
    pano_orig = Image.open(pano_path)
    scale     = PANO_DISPLAY_WIDTH / pano_orig.width
    pano_disp = pano_orig.resize((PANO_DISPLAY_WIDTH, int(pano_orig.height * scale)), Image.LANCZOS)
    slot_pano_x = {slot: st.session_state[slot] for slot in SLOTS}
    st.image(annotate_panorama(pano_disp, scale, valid["cx"].tolist(), slot_pano_x), width="stretch")
    st.caption("Blue = pose centres · Green = overlap start · Orange = overlap end · Red = azimuth ref")

# ── step 2: results ───────────────────────────────────────────────────────────
st.divider()
st.header("2 · Results")

info_ol  = st.session_state["overlap_start"]
info_or  = st.session_state["overlap_end"]
info_ref = st.session_state["az_ref"]

ready_scale = info_ol is not None and info_or is not None
ready_full  = ready_scale and info_ref is not None

if not ready_scale:
    st.info("Set the two overlap points (① and ②) to compute the scale.")
else:
    px_per_deg_overlap = (info_or["pano_x"] - info_ol["pano_x"]) / 360.0
    img_w = int(valid["img_w"].iloc[0]) if not valid.empty else 1280

    # Show scale comparison
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("px/deg — overlap (used)", f"{px_per_deg_overlap:.2f}")
    if px_per_deg_phase is not None:
        col_b.metric("px/deg — phase corr.", f"{px_per_deg_phase:.2f}")
    col_c.metric("px/deg — nominal FOV", f"{img_w / fov_deg:.2f}")

    if not ready_full:
        st.info("Set the azimuth reference point (③) and enter its azimuth.")
    else:
        result = valid.copy()
        result["az_center"] = result["cx"].apply(
            lambda cx: az_from_x(cx, ref_az, info_ref["pano_x"], px_per_deg_overlap)
        )
        cols = ["pose", "name", "az_center", "cx", "inliers", "rms"]
        fmt  = {"cx": "{:.0f}", "az_center": "{:.1f}"}
        if result["rms"].notna().any():
            fmt["rms"] = "{:.3f}"
        st.dataframe(
            result[cols].style.format(fmt, na_rep="—"),
            width="stretch", hide_index=True,
        )

        csv_path = base / cam / "calibration.csv"
        if st.button("💾 Save calibration.csv", type="primary"):
            result[cols].to_csv(csv_path, index=False)
            st.success(f"Saved → {csv_path}")

        skipped = df[df["cx"].isna()]
        if not skipped.empty:
            with st.expander(f"⚠ {len(skipped)} unmatched poses"):
                st.dataframe(skipped[["pose", "name", "error"]], hide_index=True)
