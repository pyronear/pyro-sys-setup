"""
Page 3 — Pose selection.

Browse all calibrated poses for every camera in the station.
Select which poses to use; the map shows a FOV cone for each selected pose.
Export the selection to selected_poses.json for use by pyro-engine.
"""

from pathlib import Path
import glob
import json
import math
import re
import sys
import time

import folium
import pandas as pd
from PIL import Image
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyro_camera_api_client.client import PyroCameraAPIClient

# ── constants ─────────────────────────────────────────────────────────────────
CAPTURES_DIR     = Path(__file__).parent.parent / "captures"
DEFAULT_FOV      = 54.2
DEFAULT_RANGE_KM = 10.0
THUMB_WIDTH      = 180
COLS_PER_ROW     = 5
CAM_COLORS       = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#a65628"]

st.set_page_config(page_title="Pose Selection", layout="wide")
st.title("3 · Pose selection")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")
st.sidebar.markdown(f"**Pi IP:** `{pi_ip}`")

# ── helpers ───────────────────────────────────────────────────────────────────

def pose_num(path: Path) -> int:
    m = re.search(r"pose_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def cone_coords(lat: float, lon: float, az_deg: float, fov_deg: float, range_m: float) -> list:
    """Return [[lat, lon], ...] polygon for a camera FOV cone."""
    pts = [[lat, lon]]
    half = fov_deg / 2
    for i in range(21):
        bearing = math.radians(az_deg - half + i * fov_deg / 20)
        dlat = range_m * math.cos(bearing) / 111320
        dlon = range_m * math.sin(bearing) / (111320 * math.cos(math.radians(lat)))
        pts.append([lat + dlat, lon + dlon])
    pts.append([lat, lon])
    return pts


# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    fov_deg  = st.number_input("Camera FOV (°)", value=DEFAULT_FOV, step=0.1, format="%.1f")
    range_km = st.number_input("Detection range (km)", value=DEFAULT_RANGE_KM, step=0.5, format="%.1f")

# ── discover cameras ──────────────────────────────────────────────────────────
base     = CAPTURES_DIR / pi_ip
cam_dirs = sorted(
    Path(c) for c in glob.glob(str(base / "*"))
    if (Path(c) / "calibration.csv").exists()
)

if not cam_dirs:
    st.warning(f"No calibrated cameras found under `{base}`. Run calibration first.")
    st.stop()

# ── session state init (pre-populate from saved JSON if first load) ───────────
saved_json = base / "selected_poses.json"
for cam_dir in cam_dirs:
    cid = cam_dir.name
    if f"sel_{cid}" not in st.session_state:
        if saved_json.exists():
            data = json.loads(saved_json.read_text())
            st.session_state[f"sel_{cid}"] = set(data.get(cid, {}).get("poses", {}).keys())
        else:
            st.session_state[f"sel_{cid}"] = set()
if "station_latlon" not in st.session_state:
    if saved_json.exists():
        data = json.loads(saved_json.read_text())
        first = next(iter(data.values()), {})
        lat0, lon0 = first.get("lat", 0.0), first.get("lon", 0.0)
        st.session_state["station_latlon"] = f"{lat0}, {lon0}" if lat0 or lon0 else ""
    else:
        st.session_state["station_latlon"] = ""

# ── station lat/lon (shared by all cameras) ───────────────────────────────────
latlon_str = st.text_input(
    "Station Lat, Lon (all cameras)",
    value=st.session_state["station_latlon"],
    placeholder="48.426801, 2.710724",
)
station_lat, station_lon = 0.0, 0.0
try:
    lat_s, lon_s = latlon_str.split(",")
    station_lat = float(lat_s.strip())
    station_lon = float(lon_s.strip())
    st.session_state["station_latlon"] = latlon_str
except ValueError:
    if latlon_str.strip():
        st.warning("Expected format: `lat, lon` — e.g. `48.426801, 2.710724`")

# ── per-camera sections ───────────────────────────────────────────────────────
for color, cam_dir in zip(CAM_COLORS, cam_dirs):
    cid     = cam_dir.name
    df      = pd.read_csv(cam_dir / "calibration.csv")
    img_dir = cam_dir / "images"
    selected: set = st.session_state[f"sel_{cid}"]

    st.markdown(
        f"<span style='border-left:4px solid {color}; padding-left:8px'>"
        f"**Camera `{cid}`** — {len(selected)} pose(s) selected</span>",
        unsafe_allow_html=True,
    )

    lat, lon = station_lat, station_lon

    poses = df.sort_values("pose").to_dict("records")
    cols  = st.columns(COLS_PER_ROW)

    for i, row in enumerate(poses):
        img_path = img_dir / row["name"]
        with cols[i % COLS_PER_ROW]:
            if img_path.exists():
                img = Image.open(img_path)
                img.thumbnail((THUMB_WIDTH, THUMB_WIDTH))
                st.image(img)
            is_sel = row["name"] in selected
            checked = st.checkbox(
                f"{'✓ ' if is_sel else ''}{row['pose']} · {row['az_center']:.0f}°",
                value=is_sel,
                key=f"chk_{cid}_{row['name']}",
            )
            if checked:
                selected.add(row["name"])
            else:
                selected.discard(row["name"])

    # ── set presets ───────────────────────────────────────────────────────────
    selected_sorted = sorted(selected, key=lambda n: pose_num(Path(n)))

    if selected_sorted:
        confirm_key = f"confirm_preset_{cid}"
        if confirm_key not in st.session_state:
            st.session_state[confirm_key] = False

        mapping = ", ".join(
            f"{pose_num(Path(n))}→{i}" for i, n in enumerate(selected_sorted)
        )

        if not st.session_state[confirm_key]:
            if st.button(f"Set presets on {cid}", key=f"btn_preset_{cid}"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning(
                f"Will overwrite presets **0–{len(selected_sorted) - 1}** on `{cid}`  \n"
                f"Mapping: {mapping}"
            )
            col_ok, col_cancel = st.columns(2)
            with col_ok:
                if st.button("Confirm", key=f"confirm_btn_{cid}", type="primary", width="stretch"):
                    with st.status(f"Setting presets on {cid}…", expanded=True) as status:
                        client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=30.0)
                        try:
                            st.write("Starting stream…")
                            client.start_stream(cid)
                            time.sleep(2)
                            for new_idx, pose_name in enumerate(selected_sorted):
                                orig = pose_num(Path(pose_name))
                                st.write(f"Moving to pose {orig} → preset {new_idx}…")
                                client.move_camera(cid, pose_id=orig)
                                time.sleep(2)
                                client.set_preset(cid, idx=new_idx)
                            status.update(label=f"Done — {len(selected_sorted)} presets set.", state="complete")
                        except Exception as e:
                            status.update(label=f"Error: {e}", state="error")
                        finally:
                            client.stop_stream()
                    st.session_state[confirm_key] = False
            with col_cancel:
                if st.button("Cancel", key=f"cancel_btn_{cid}", width="stretch"):
                    st.session_state[confirm_key] = False
                    st.rerun()

    st.divider()

# ── map ───────────────────────────────────────────────────────────────────────
st.header("Map")

if not station_lat and not station_lon:
    st.info("Enter the station latitude/longitude above to show the map.")
else:
    m = folium.Map(location=[station_lat, station_lon], zoom_start=12)
    range_m = range_km * 1000

    for i, cam_dir in enumerate(cam_dirs):
        cid      = cam_dir.name
        color    = CAM_COLORS[i % len(CAM_COLORS)]
        lat, lon = station_lat, station_lon
        df       = pd.read_csv(cam_dir / "calibration.csv")
        selected = st.session_state[f"sel_{cid}"]

        folium.CircleMarker(
            [lat, lon], radius=8,
            color=color, fill=True, fill_color=color, fill_opacity=1.0,
            tooltip=cid,
        ).add_to(m)

        for pose_name in selected:
            row = df[df["name"] == pose_name]
            if row.empty:
                continue
            az = float(row.iloc[0]["az_center"])
            folium.Polygon(
                cone_coords(lat, lon, az, fov_deg, range_m),
                color=color, fill=True, fill_color=color,
                fill_opacity=0.15, weight=1.5,
                tooltip=f"{cid} · {pose_name} · {az:.0f}°",
            ).add_to(m)

    st_folium(m, width="100%", height=550, returned_objects=[])

# ── export ────────────────────────────────────────────────────────────────────
st.divider()
total_selected = sum(len(st.session_state[f"sel_{d.name}"]) for d in cam_dirs)
if st.button(f"Export {total_selected} selected pose(s) → selected_poses.json",
             type="primary", disabled=total_selected == 0):
    out = {}
    for cam_dir in cam_dirs:
        cid      = cam_dir.name
        selected = st.session_state[f"sel_{cid}"]
        if not selected:
            continue
        df = pd.read_csv(cam_dir / "calibration.csv")
        out[cid] = {
            "lat": station_lat,
            "lon": station_lon,
            "poses": {
                row["name"]: round(float(row["az_center"]), 2)
                for _, row in df.iterrows()
                if row["name"] in selected
            },
        }
    out_path = base / "selected_poses.json"
    out_path.write_text(json.dumps(out, indent=2))
    st.success(f"Saved → {out_path}")
