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

st.title("Camera azimuth calibration")
st.markdown("""
Use the pages in the sidebar to go through the calibration workflow:

1. **Single capture** — preview each camera, manually fine-tune pose 10 (sweep start)
2. **Sweep & panorama** — sweep all PTZ cameras and stitch panoramas
3. **Calibration** — click reference landmarks on the panorama, export `calibration.csv`
4. **Pose selection** — pick poses to use, push them as presets, export `selected_poses.json`
""")
