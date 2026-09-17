"""
Page 0 — Pose capture.

  • Go to any pose ID and capture one image to check the framing
  • Run a capture loop: from a starting pose, step N degrees, saving each
    image locally and storing the position as a preset
"""

from pathlib import Path
import sys
import time

import streamlit as st

from pyro_camera_api_client.client import PyroCameraAPIClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture_poses import capture_one, capture_poses, pose_dir

st.set_page_config(page_title="Pose capture", layout="wide")
st.title("0 · Pose capture")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")
st.sidebar.markdown(f"**Pi IP:** `{pi_ip}`")
st.sidebar.caption("Change in the Home page.")


@st.cache_data(ttl=30, show_spinner="Fetching camera list…")
def fetch_cameras(pi_ip: str):
    client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=15.0)
    return client.get_camera_infos().get("cameras", [])


if st.button("Connect / Refresh camera list"):
    st.cache_data.clear()

try:
    cameras = [c for c in fetch_cameras(pi_ip) if c.get("type") == "ptz"]
except Exception as e:
    st.error(f"Cannot reach {pi_ip}:8081 — {e}")
    st.stop()

if not cameras:
    st.warning("No PTZ camera found.")
    st.stop()

cam_ip = st.selectbox(
    "Camera",
    [c["camera_id"] for c in cameras],
    format_func=lambda ip: f"{ip} — {next(c.get('name', ip) for c in cameras if c['camera_id'] == ip)}",
)
out_dir = pose_dir(pi_ip, cam_ip)
client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=60.0)

# ── go to a pose & check ──────────────────────────────────────────────────────
st.subheader("Go to a pose")
col_pose, col_go, col_shot = st.columns([1, 1, 1])
with col_pose:
    goto_pose = st.number_input("Pose ID", value=39, step=1, min_value=1)
with col_go:
    st.write("")
    if st.button("▶️ Go to pose", width="stretch"):
        try:
            client.stop_patrol(cam_ip)
            client.goto_preset(cam_ip, pose_id=int(goto_pose), speed=64)
            time.sleep(3)
            st.success(f"At pose {int(goto_pose)}")
        except Exception as e:
            st.error(f"Move failed: {e}")
with col_shot:
    st.write("")
    if st.button("📷 Capture check image", width="stretch"):
        with st.spinner("Capturing…"):
            try:
                client.start_stream(cam_ip)
                time.sleep(2)
                st.session_state["check_img"] = capture_one(
                    client, cam_ip, out_dir.parent / "checks", pose=int(goto_pose), width=1280
                )
            except Exception as e:
                st.error(f"Capture failed: {e}")
            finally:
                try:
                    client.stop_stream()
                except Exception:
                    pass

check_img = st.session_state.get("check_img")
if check_img and Path(check_img).exists():
    st.image(str(check_img), caption=str(check_img), width="stretch")

# ── capture loop ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("Capture loop")

c1, c2, c3, c4 = st.columns(4)
start_pose = c1.number_input("Start pose", value=20, step=1, min_value=1)
step_deg = c2.number_input("Step (°)", value=12.5, step=0.5, min_value=0.1, format="%.1f")
n_captures = c3.number_input("Captures", value=35, step=1, min_value=1)
direction = c4.selectbox("Direction", ["Right", "Left"])

c5, c6 = st.columns(2)
width = c5.selectbox("Image width (px)", [1280, 1920, 2560], index=0)
settle = c6.number_input("Settle after move (s)", value=2.0, step=0.5, min_value=0.0)

st.caption(f"→ poses {int(start_pose)}–{int(start_pose) + int(n_captures) - 1} saved in `{out_dir}` "
           "(previous images of this camera are deleted first)")

if st.button("🎬 Run capture loop", type="primary", width="stretch"):
    progress = st.progress(0.0)
    preview = st.empty()
    with st.status("Capturing poses…", expanded=True) as status:
        try:
            client.stop_patrol(cam_ip)
            client.start_stream(cam_ip)
            time.sleep(2)

            def on_pose(i, pose, path):
                progress.progress((i + 1) / int(n_captures))
                if path is None:
                    st.write(f"  ✗ pose {pose} — capture failed, skipped")
                    return
                st.write(f"  ✓ pose {pose} → {path.name}")
                preview.image(str(path), caption=f"pose {pose}", width=480)

            capture_poses(
                client, cam_ip, out_dir,
                start_pose=int(start_pose), step_deg=float(step_deg),
                n_captures=int(n_captures), direction=direction,
                width=int(width), settle=float(settle), on_pose=on_pose,
            )
            status.update(label=f"Done — {int(n_captures)} images in {out_dir}", state="complete")
        except Exception as e:
            status.update(label=f"Error: {e}", state="error")
        finally:
            try:
                client.stop_stream()
            except Exception:
                pass
