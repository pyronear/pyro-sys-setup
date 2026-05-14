"""
Page 1 — Single image capture & pose 10 adjustment.

Use this page to:
  • Preview the current view of each camera (quick or full quality)
  • Manually fine-tune the starting position (pose 10) used by the sweep
"""

import concurrent.futures
from pathlib import Path
import sys

import streamlit as st
from PIL import Image

from pyro_camera_api_client.client import PyroCameraAPIClient

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── config ───────────────────────────────────────────────────────────────────
CAPTURES_DIR = Path(__file__).parent.parent / "captures"
PREVIEW_QUALITY = 80

st.set_page_config(page_title="Single capture", layout="wide")
st.title("1 · Single capture & pose adjustment")

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

# ── batch actions (all cameras) ───────────────────────────────────────────────
col_prev, col_one = st.columns(2)

with col_prev:
    if st.button(f"📸 Quick preview (q={PREVIEW_QUALITY})", width="stretch"):
        preview_client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=30.0)
        with st.status("Capturing previews…", expanded=True) as status:
            for cam in cameras:
                cam_ip = cam["camera_id"]
                try:
                    jpeg = preview_client.capture_jpeg(cam_ip, anonymize=False, quality=PREVIEW_QUALITY)
                    preview_path = CAPTURES_DIR / pi_ip / cam_ip / "preview.jpg"
                    preview_path.parent.mkdir(parents=True, exist_ok=True)
                    preview_path.write_bytes(jpeg)
                    st.write(f"  ✓ {cam_ip} — {len(jpeg) // 1024} KB")
                except Exception as e:
                    st.write(f"  ✗ {cam_ip} — {e}")
            status.update(label="Previews complete!", state="complete")
        st.rerun()

with col_one:
    if st.button("📷 Single image (parallel)", width="stretch"):
        def _capture_one(cam):
            cam_ip = cam["camera_id"]
            c = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=30.0)
            jpeg = c.capture_jpeg(cam_ip, anonymize=False)
            p = CAPTURES_DIR / pi_ip / cam_ip / "preview.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(jpeg)
            return len(jpeg)

        with st.status("Capturing one image from all cameras…", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cameras))) as ex:
                futures = {ex.submit(_capture_one, cam): cam for cam in cameras}
                for fut in concurrent.futures.as_completed(futures):
                    cam = futures[fut]
                    try:
                        size = fut.result()
                        st.write(f"  ✓ {cam['camera_id']} — {size // 1024} KB")
                    except Exception as e:
                        st.write(f"  ✗ {cam['camera_id']} — {e}")
            status.update(label="Done!", state="complete")
        st.rerun()

# ── per-camera cards ──────────────────────────────────────────────────────────
for cam in cameras:
    cam_ip   = cam["camera_id"]
    cam_name = cam.get("name", cam_ip)
    cam_type = cam.get("type", "static")
    preview_path = CAPTURES_DIR / pi_ip / cam_ip / "preview.jpg"

    with st.expander(
        f"{'📷' if cam_type == 'static' else '🔄'} **{cam_name}** — `{cam_ip}` [{cam_type}]",
        expanded=True,
    ):
        col_info, col_actions = st.columns([2, 1])

        with col_info:
            if preview_path.exists():
                preview = Image.open(preview_path)
                w, h = preview.size
                st.image(preview, caption=f"preview.jpg ({w}×{h})", width="stretch")
            else:
                st.info("No preview yet.")

        with col_actions:
            client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=30.0)

            # ── per-camera preview ────────────────────────────────────────
            if st.button(f"Preview (q={PREVIEW_QUALITY})", key=f"prev_{cam_ip}", width="stretch"):
                with st.spinner(f"Capturing preview from {cam_name}…"):
                    try:
                        jpeg = client.capture_jpeg(cam_ip, anonymize=False, quality=PREVIEW_QUALITY)
                        preview_path.parent.mkdir(parents=True, exist_ok=True)
                        preview_path.write_bytes(jpeg)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Preview failed: {e}")

            # ── manual pose 10 adjustment ─────────────────────────────────
            if cam_type == "ptz":
                st.divider()
                st.markdown("**Adjust pose 10**")

                if st.button("Go to pose 10", key=f"goto_p10_{cam_ip}", width="stretch"):
                    try:
                        client.stop_patrol(cam_ip)
                        client.goto_preset(cam_ip, pose_id=10)
                    except Exception as e:
                        st.error(f"Move failed: {e}")

                col_dir, col_deg = st.columns(2)
                with col_dir:
                    nudge_dir = st.selectbox(
                        "Direction", ["Left", "Right", "Up", "Down"],
                        key=f"nudge_dir_{cam_ip}",
                    )
                with col_deg:
                    nudge_deg = st.number_input(
                        "Degrees", value=5.0, step=0.5,
                        min_value=0.1, max_value=180.0,
                        key=f"nudge_deg_{cam_ip}",
                    )

                if st.button(f"Move {nudge_deg:.1f}° {nudge_dir}",
                             key=f"nudge_{cam_ip}", width="stretch"):
                    try:
                        client.move_by_degrees(cam_ip, direction=nudge_dir, degrees=float(nudge_deg))
                    except Exception as e:
                        st.error(f"Move failed: {e}")

                if st.button("💾 Save as pose 10", key=f"save_p10_{cam_ip}", width="stretch"):
                    try:
                        client.set_preset(cam_ip, idx=10)
                        st.success("Saved as pose 10")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
