"""
Page 0 — Pose capture.

  • Go to any pose ID and capture one image to check the framing
  • Run a capture loop: from a starting pose, step N degrees, saving each
    image locally and storing the position as a preset
"""

from pathlib import Path
import queue
import sys
import threading
import time

import streamlit as st

from pyro_camera_api_client.client import PyroCameraAPIClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture_poses import capture_in_parallel, capture_one, pose_dir

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
                st.session_state["check_img"] = capture_one(
                    client, cam_ip, out_dir.parent / "checks", pose=int(goto_pose), width=1280
                )
            except Exception as e:
                st.error(f"Capture failed: {e}")

n1, n2, n3 = st.columns([1, 1, 1])
nudge = n1.number_input("Nudge (°)", value=5.0, step=1.0, min_value=0.5,
                        help="Aim the camera before a sweep that starts from here.")
for col, label, side in ((n2, "◀ Left", "Left"), (n3, "▶ Right", "Right")):
    with col:
        st.write("")
        if st.button(label, width="stretch", key=f"nudge_{side}"):
            try:
                client.stop_patrol(cam_ip)
                client.move_by_degrees(cam_ip, direction=side, degrees=float(nudge))
            except Exception as e:
                st.error(f"Move failed: {e}")

check_img = st.session_state.get("check_img")
if check_img and Path(check_img).exists():
    st.image(str(check_img), caption=str(check_img), width="stretch")

# ── capture loop ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("Capture loop")

all_ptz = [c["camera_id"] for c in cameras]
loop_cams = st.multiselect("Cameras (captured in parallel)", all_ptz, default=all_ptz)

from_presets = st.radio(
    "Mode", ["Sweep", "Recapture"], horizontal=True,
    help="Sweep: rotate by the step from the start pose and store each position "
         "as a preset. Recapture: go to each existing preset and take a fresh "
         "image, nothing moves by step and no preset is written.") == "Recapture"

c1, c2, c3, c4 = st.columns(4)
start_pose = c1.number_input("Start pose", value=20, step=1, min_value=1)
step_deg = c2.number_input("Step (°)", value=12.5, step=0.5, min_value=0.1, format="%.1f",
                           disabled=from_presets)
n_captures = c3.number_input("Captures", value=35, step=1, min_value=1)
direction = c4.selectbox("Direction", ["Right", "Left"], disabled=from_presets)

c5, c6 = st.columns(2)
width = c5.selectbox("Image width (px)", [1280, 1920, 2560], index=0)
settle = c6.number_input("Settle after move (s)", value=3.0 if from_presets else 2.0,
                         step=0.5, min_value=0.0)
from_current = (not from_presets) and st.checkbox(
    "Start from where the camera is now",
    help="Skip going to the start preset first: aim the camera with the nudge "
         "buttons above, the sweep starts here and stores it as the start pose. "
         "Needed on a camera that has no presets yet.")

st.caption(f"→ poses {int(start_pose)}–{int(start_pose) + int(n_captures) - 1} saved in "
           f"`{pose_dir(pi_ip, '<cam>')}` (previous images of each camera are deleted first)"
           + (" — from the presets already on the camera" if from_presets else ""))

# The run lives in session state: the capture threads only push events to a
# queue (Streamlit widgets are not usable from other threads) and the page
# redraws itself every second while they work, so a Stop button stays live.
run = st.session_state.get("capture_run")
running = bool(run and run["worker"].is_alive())

if st.button("🎬 Recapture existing poses" if from_presets else "🎬 Run capture loop",
             type="primary", width="stretch", disabled=not loop_cams or running):
    for cam in loop_cams:
        client.stop_patrol(cam)
    events, results, stop = queue.Queue(), {}, threading.Event()
    worker = threading.Thread(
        target=lambda: results.update(capture_in_parallel(
            client, loop_cams, lambda cam: pose_dir(pi_ip, cam),
            on_pose=lambda cam, i, pose, path: events.put((cam, i, pose, path)),
            start_pose=int(start_pose), step_deg=float(step_deg),
            n_captures=int(n_captures), direction=direction,
            width=int(width), settle=float(settle), from_presets=from_presets,
            from_current=from_current, stop=stop)),
        daemon=True)
    worker.start()
    st.session_state["capture_run"] = run = {
        "worker": worker, "events": events, "results": results, "stop": stop,
        "cams": loop_cams, "n": int(n_captures), "last": {}}
    running = True

if run:
    while True:                                   # drain what the threads sent
        try:
            cam, i, pose, path = run["events"].get_nowait()
        except queue.Empty:
            break
        run["last"][cam] = (i, pose, path)

    if running and st.button("⏹ Stop after the current pose", width="stretch"):
        run["stop"].set()

    for col, cam in zip(st.columns(len(run["cams"])), run["cams"]):
        with col:
            st.markdown(f"**{cam}**")
            if cam not in run["last"]:
                st.progress(0.0)
                continue
            i, pose, path = run["last"][cam]
            st.progress((i + 1) / run["n"])
            if path is None:
                st.write(f"✗ pose {pose} — capture failed, skipped")
            else:
                st.write(f"✓ {i + 1}/{run['n']} · pose {pose} → {path.name}")
                st.image(str(path), caption=f"pose {pose}", width="stretch")

    if running:
        st.caption("stopping…" if run["stop"].is_set() else "capturing…")
        time.sleep(1)
        st.rerun()

    for cam, r in run["results"].items():
        if isinstance(r, Exception):
            st.error(f"{cam}: {r}")
        else:
            done = sum(p is not None for p in r)
            st.success(f"{cam}: {done}/{len(r)} images in {pose_dir(pi_ip, cam)}"
                       + (f" — stopped after {len(r)} of {run['n']} poses" if len(r) < run["n"] else ""))
