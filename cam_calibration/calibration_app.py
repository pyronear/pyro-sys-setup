"""
Streamlit app for camera azimuth calibration.

- Browse pose images with prev/next
- Click a landmark on the current pose image
- Enter the known azimuth for that point
- Azimuths are computed for all poses and saved to calibration.csv
"""

from pathlib import Path
import glob
import re

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

# ── constants ────────────────────────────────────────────────────────────────
PANO_DISPLAY_WIDTH = 1400
MIN_INLIERS = 20
RANSAC_THRESH = 3.0

# ── helpers ──────────────────────────────────────────────────────────────────

def pose_num(path: Path) -> int:
    m = re.search(r"pose_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def load_bgr(path: Path) -> np.ndarray:
    im = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(str(path))
    return im


def match_knn(desc1, desc2):
    index_params = dict(algorithm=1, trees=5)
    search_params = dict(checks=100)
    matcher = cv2.FlannBasedMatcher(index_params, search_params)
    matches = matcher.knnMatch(desc1, desc2, k=2)
    return [m for m, n in matches if m.distance < 0.75 * n.distance]


def find_homography(kp1, kp2, matches):
    if len(matches) < 12:
        return None, 0, None
    src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, RANSAC_THRESH)
    if H is None or mask is None:
        return None, 0, None
    inliers = mask.ravel().astype(bool)
    proj = cv2.perspectiveTransform(src_pts[inliers], H)
    rms = float(np.sqrt((np.linalg.norm(proj - dst_pts[inliers], axis=2) ** 2).mean()))
    return H, int(inliers.sum()), rms


def project_point(x: float, y: float, H: np.ndarray) -> tuple[float, float]:
    pt = np.float32([[[x, y]]])
    out = cv2.perspectiveTransform(pt, H)[0, 0]
    return float(out[0]), float(out[1])


def az_from_x(x, img_width_px, ref_azimuth, ref_pixel, fov_deg):
    px_per_deg = img_width_px / fov_deg
    return (ref_azimuth + (x - ref_pixel) / px_per_deg) % 360.0


def annotate_pose(img: Image.Image, click_x: int | None, click_y: int | None) -> Image.Image:
    out = img.copy()
    if click_x is None:
        return out
    draw = ImageDraw.Draw(out)
    r = 16
    draw.line([(click_x - r, click_y), (click_x + r, click_y)], fill=(255, 50, 50), width=3)
    draw.line([(click_x, click_y - r), (click_x, click_y + r)], fill=(255, 50, 50), width=3)
    draw.ellipse([(click_x - r, click_y - r), (click_x + r, click_y + r)],
                 outline=(255, 50, 50), width=2)
    return out


def annotate_panorama(pano: Image.Image, ref_pixel_orig: int | None,
                      scale: float, cx_list: list[float]) -> Image.Image:
    img = pano.copy()
    draw = ImageDraw.Draw(img)
    h = img.height
    for cx in cx_list:
        x = int(cx * scale)
        draw.line([(x, 0), (x, h)], fill=(100, 149, 237), width=2)
    if ref_pixel_orig is not None:
        x = int(ref_pixel_orig * scale)
        r = 14
        draw.line([(x - r, h // 2), (x + r, h // 2)], fill=(255, 50, 50), width=3)
        draw.line([(x, h // 2 - r), (x, h // 2 + r)], fill=(255, 50, 50), width=3)
        draw.ellipse([(x - r, h // 2 - r), (x + r, h // 2 + r)],
                     outline=(255, 50, 50), width=2)
    return img


# ── cached heavy work ────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Matching poses against panorama…")
def compute_pose_positions(pano_path: str, image_paths: list[str]):
    """Returns (df, homographies_dict) where homographies_dict maps name→H."""
    pano = load_bgr(Path(pano_path))
    extractor = cv2.SIFT_create(nfeatures=6000)
    kp_pano, des_pano = extractor.detectAndCompute(pano, None)
    img_width_px = load_bgr(Path(image_paths[0])).shape[1]

    rows, homographies = [], {}
    for p_str in image_paths:
        p = Path(p_str)
        src = load_bgr(p)
        kp_src, des_src = extractor.detectAndCompute(src, None)
        if des_src is None or len(kp_src) < 8:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=None, cy=None,
                             inliers=0, rms=None, error="few features", img_width_px=img_width_px))
            continue
        good = match_knn(des_src, des_pano)
        H, n_in, rms = find_homography(kp_src, kp_pano, good)
        if H is None or n_in < MIN_INLIERS:
            rows.append(dict(name=p.name, pose=pose_num(p), cx=None, cy=None,
                             inliers=n_in, rms=None, error=f"{n_in} inliers", img_width_px=img_width_px))
            continue
        h_img, w_img = src.shape[:2]
        cx, cy = project_point(w_img * 0.5, h_img * 0.5, H)
        rows.append(dict(name=p.name, pose=pose_num(p), cx=cx, cy=cy,
                         inliers=n_in, rms=rms, error=None, img_width_px=img_width_px))
        homographies[p.name] = H

    df = pd.DataFrame(rows).sort_values("pose").reset_index(drop=True)
    return df, homographies


# ── app ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Azimuth calibration", layout="wide")
st.title("Camera azimuth calibration")

# ── sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Configuration")
    pi_ip = st.text_input("Pi VPN IP", "192.168.255.106")
    base = Path("captures") / pi_ip

    cam_dirs = sorted(
        Path(c).name for c in glob.glob(str(base / "*"))
        if (Path(c) / "images").is_dir()
    )
    if not cam_dirs:
        st.error(f"No captures found under {base}")
        st.stop()

    cam = st.selectbox("Camera", cam_dirs)
    fov_deg = st.number_input("Camera FOV (°)", value=54.2, step=0.1, format="%.1f")

folder = base / cam / "images"
pano_path = base / cam / "panorama_full.jpg"

if not pano_path.exists():
    st.error(f"Panorama not found: {pano_path}  — run compute_panorama.py first.")
    st.stop()

image_paths = sorted(
    [str(p) for p in folder.glob("*.jpg") if not p.name.startswith("panorama")],
    key=lambda s: pose_num(Path(s)),
)
if not image_paths:
    st.error(f"No pose images found in {folder}")
    st.stop()

# ── session state ─────────────────────────────────────────────────────────────
for key, default in [("pose_idx", 0), ("ref_pixel_orig", None),
                     ("click_x", None), ("click_y", None), ("ref_pose_name", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── compute matches (cached) ──────────────────────────────────────────────────
df, homographies = compute_pose_positions(str(pano_path), image_paths)
valid = df[df["cx"].notna()]

# ── step 1: browse poses & click reference ────────────────────────────────────
st.header("1 · Navigate to a pose and click a reference landmark")
st.caption("Use the buttons to find a pose where you can identify a landmark with a known azimuth. "
           "Click that landmark on the image, then enter its azimuth below.")

total = len(image_paths)
idx = st.session_state.pose_idx

col_prev, col_label, col_next = st.columns([1, 4, 1])
with col_prev:
    if st.button("← Prev", width="stretch") and idx > 0:
        st.session_state.pose_idx -= 1
        st.rerun()
with col_next:
    if st.button("Next →", width="stretch") and idx < total - 1:
        st.session_state.pose_idx += 1
        st.rerun()
with col_label:
    st.markdown(f"**{Path(image_paths[idx]).name}** &nbsp; ({idx + 1} / {total})")

current_path = Path(image_paths[idx])
current_name = current_path.name
current_row = df[df["name"] == current_name]
has_H = current_name in homographies

col_img, col_ref = st.columns([3, 1])

with col_img:
    pose_pil = Image.open(current_path)
    pose_w, pose_h = pose_pil.size

    # draw crosshair if click was on this pose
    click_x = st.session_state.click_x if st.session_state.ref_pose_name == current_name else None
    click_y = st.session_state.click_y if st.session_state.ref_pose_name == current_name else None
    annotated_pose = annotate_pose(pose_pil, click_x, click_y)

    if has_H:
        click = streamlit_image_coordinates(annotated_pose, key=f"pose_click_{current_name}")
        if click is not None and (click["x"] != click_x or click["y"] != click_y):
            st.session_state.click_x = click["x"]
            st.session_state.click_y = click["y"]
            st.session_state.ref_pose_name = current_name
            # project click through H to get panorama x
            H = homographies[current_name]
            pano_x, _ = project_point(click["x"], click["y"], H)
            st.session_state.ref_pixel_orig = int(pano_x)
            st.rerun()
    else:
        st.image(annotated_pose, width="stretch")
        reason = current_row.iloc[0]["error"] if not current_row.empty else "unknown"
        st.warning(f"This pose could not be matched ({reason}) — choose another pose to set the reference.")

with col_ref:
    st.markdown("**Reference point**")
    ref_azimuth = st.number_input(
        "Azimuth (°)", min_value=0.0, max_value=360.0,
        value=0.0, step=0.1, format="%.1f", key="ref_az_input",
    )
    if st.session_state.ref_pixel_orig is not None:
        st.metric("Panorama x", st.session_state.ref_pixel_orig)
        st.caption(f"Set from **{st.session_state.ref_pose_name}**")
        if st.button("Clear", width="stretch"):
            st.session_state.ref_pixel_orig = None
            st.session_state.click_x = None
            st.session_state.click_y = None
            st.session_state.ref_pose_name = None
            st.rerun()
    else:
        st.info("Click a landmark on the image.")

# ── panorama overview ─────────────────────────────────────────────────────────
with st.expander("Panorama overview"):
    pano_orig = Image.open(pano_path)
    pano_w, pano_h = pano_orig.size
    scale = PANO_DISPLAY_WIDTH / pano_w
    pano_display = pano_orig.resize((PANO_DISPLAY_WIDTH, int(pano_h * scale)), Image.LANCZOS)
    cx_list = valid["cx"].tolist()
    annotated_pano = annotate_panorama(pano_display, st.session_state.ref_pixel_orig, scale, cx_list)
    st.image(annotated_pano, width="stretch")
    st.caption("Blue lines = pose centres · Red crosshair = reference point")

# ── step 2: results & export ──────────────────────────────────────────────────
st.divider()
st.header("2 · Results")

if st.session_state.ref_pixel_orig is None:
    st.info("Click a landmark in step 1 to compute azimuths.")
else:
    img_w_col = int(valid["img_width_px"].iloc[0]) if not valid.empty else 1280
    result = valid.copy()
    result["az_center"] = result["cx"].apply(
        lambda cx: az_from_x(cx, img_w_col, ref_azimuth,
                              st.session_state.ref_pixel_orig, fov_deg)
    )
    display_cols = ["pose", "name", "az_center", "cx", "inliers", "rms"]
    st.dataframe(
        result[display_cols].style.format(
            {"cx": "{:.0f}", "az_center": "{:.1f}", "rms": "{:.3f}"}
        ),
        width="stretch",
        hide_index=True,
    )

    csv_path = base / cam / "calibration.csv"
    if st.button("💾 Save calibration.csv", type="primary"):
        result[display_cols].to_csv(csv_path, index=False)
        st.success(f"Saved → {csv_path}")

    skipped = df[df["cx"].isna()]
    if not skipped.empty:
        with st.expander(f"⚠ {len(skipped)} unmatched poses"):
            st.dataframe(skipped[["pose", "name", "error"]], hide_index=True)
