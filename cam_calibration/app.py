"""
Pyronear camera calibration — main entry point.

Run with:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Pyronear calibration", layout="wide", page_icon="🔥")

# ── shared config (persists across pages via session_state) ──────────────────
with st.sidebar:
    st.title("🔥 Pyronear calibration")
    st.divider()
    pi_ip = st.text_input("Pi VPN IP", st.session_state.get("pi_ip", "192.168.255.62"))
    st.session_state["pi_ip"] = pi_ip
    st.caption("Set the Pi IP once — all pages use it.")

st.title("Camera calibration")
st.markdown("""
Set the Pi IP in the sidebar, then use the pages:

0. **Pose capture** — go to a pose to check it, then capture a loop of poses
   (start pose + step in °): each image is saved locally and the position is
   stored as a camera preset.
1. **Pose calibration** — measure the real rotation of every step, fit the real
   FOV by loop closure, anchor on one known landmark, export `calibration.csv`.
2. **Pose selection** — pick the poses to patrol, check the sector they cover on
   a map, push them as presets and export `selected_poses.json`.
""")
