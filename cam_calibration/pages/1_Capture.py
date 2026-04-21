"""
Page 1 — Capture images and compute panoramas.
"""

from pathlib import Path
import sys
import time

import streamlit as st
from PIL import Image

from pyro_camera_api_client.client import PyroCameraAPIClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from compute_panorama import process_camera
from get_images_calibration import sweep_ptz, capture_static

# ── config ───────────────────────────────────────────────────────────────────
CAPTURES_DIR = Path(__file__).parent.parent / "captures"
DEFAULT_FOV   = 54.2
DEFAULT_STEP  = 20.0

st.set_page_config(page_title="Capture", layout="wide")
st.title("1 · Capture & Panorama")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")
st.sidebar.markdown(f"**Pi IP:** `{pi_ip}`")
st.sidebar.caption("Change in the Home page.")

# ── connect ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner="Fetching camera list…")
def fetch_cameras(pi_ip: str):
    client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=15.0)
    return client.get_camera_infos().get("cameras", [])

if st.button("Connect / Refresh camera list"):
    st.cache_data.clear()

cameras = []
try:
    cameras = fetch_cameras(pi_ip)
except Exception as e:
    st.error(f"Cannot reach {pi_ip}:8081 — {e}")
    st.stop()

if not cameras:
    st.warning("No cameras found.")
    st.stop()

st.success(f"Found {len(cameras)} camera(s)")

# ── per-camera cards ──────────────────────────────────────────────────────────
fov_deg  = st.sidebar.number_input("Camera FOV (°)", value=DEFAULT_FOV, step=0.1, format="%.1f")
step_deg = st.sidebar.number_input("PTZ step (°)",   value=DEFAULT_STEP, step=1.0, format="%.1f")

for cam in cameras:
    cam_ip   = cam["camera_id"]
    cam_name = cam.get("name", cam_ip)
    cam_type = cam.get("type", "static")
    out_dir  = CAPTURES_DIR / pi_ip / cam_ip / "images"
    pano_path = CAPTURES_DIR / pi_ip / cam_ip / "panorama_full.jpg"

    n_images = len(list(out_dir.glob("*.jpg"))) if out_dir.exists() else 0

    with st.expander(f"{'📷' if cam_type == 'static' else '🔄'} **{cam_name}** — `{cam_ip}` [{cam_type}]  ·  {n_images} images captured", expanded=True):
        col_info, col_actions = st.columns([2, 1])

        with col_info:
            if pano_path.exists():
                pano = Image.open(pano_path)
                w, h = pano.size
                st.image(pano, caption=f"panorama_full.jpg ({w}×{h})", width="stretch")
            elif n_images > 0:
                st.info(f"{n_images} images captured — compute panorama to preview.")
            else:
                st.info("No images yet.")

        with col_actions:
            client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=30.0)

            pose_id = st.number_input("Initial pose ID", value=30, step=1,
                                      key=f"pose_id_{cam_ip}")

            # ── capture ───────────────────────────────────────────────────
            if st.button("Capture images", key=f"cap_{cam_ip}", width="stretch"):
                with st.status(f"Capturing {cam_name}…", expanded=True) as status:
                    try:
                        st.write("Starting stream…")
                        client.start_stream(cam_ip)
                        time.sleep(2)
                        st.write(f"Setting preset {pose_id}…")
                        client.set_preset(cam_ip, idx=int(pose_id))
                        if cam_type == "ptz":
                            sweep_ptz(client, pi_ip, cam)
                        else:
                            capture_static(client, pi_ip, cam)
                        status.update(label="Capture complete!", state="complete")
                        st.rerun()
                    except Exception as e:
                        status.update(label=f"Error: {e}", state="error")
                    finally:
                        client.stop_stream()

            # ── panorama ──────────────────────────────────────────────────
            if cam_type == "ptz" and n_images >= 2:
                if st.button("Compute panorama", key=f"pano_{cam_ip}", width="stretch"):
                    with st.status("Stitching panorama…", expanded=True) as status:
                        try:
                            folder = CAPTURES_DIR / pi_ip / cam_ip / "images"
                            process_camera(folder, fov_deg, step_deg)
                            status.update(label="Panorama saved!", state="complete")
                            st.rerun()
                        except Exception as e:
                            status.update(label=f"Error: {e}", state="error")
