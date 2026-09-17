"""
Page 2 — Pose selection.

Pick the poses the camera will actually patrol, check the sector they cover on
a map, push them as presets 0..N-1 and export them for pyro-engine.

The FOV comes from `calibration.csv`, measured on that camera — the cones on
the map are the real ones, not a datasheet drawing.
"""

import csv
import json
import math
from pathlib import Path
import sys
import time

import pydeck as pdk
import streamlit as st
from PIL import Image

from pyro_camera_api_client.client import PyroCameraAPIClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from capture_poses import CAPTURES_DIR
from pixel_shift import latest_per_pose
from pose_azimuth import blind_gaps

DEFAULT_RANGE_KM = 10.0
THUMB_WIDTH = 180
COLS_PER_ROW = 6
# one colour per camera, as (r, g, b) for the map and hex for the headings
CAM_COLORS = [((228, 26, 28), "#e41a1c"), ((55, 126, 184), "#377eb8"),
              ((77, 175, 74), "#4daf4a"), ((152, 78, 163), "#984ea3"),
              ((255, 127, 0), "#ff7f00"), ((166, 86, 40), "#a65628")]

st.set_page_config(page_title="Pose selection", layout="wide")
st.title("2 · Pose selection")

pi_ip = st.session_state.get("pi_ip", "192.168.255.62")
base = CAPTURES_DIR / pi_ip
cam_dirs = sorted(d for d in base.glob("*") if (d / "calibration.csv").exists())
if not cam_dirs:
    st.error(f"No calibrated camera under `{base}` — run page 1 first.")
    st.stop()


def read_calibration(cam_dir: Path):
    """(poses sorted by azimuth order, fov). calibration.csv is written by page 1."""
    with (cam_dir / "calibration.csv").open() as f:
        rows = [{"pose": int(r["pose"]), "az": float(r["az_center"]),
                 "fov": float(r["fov_deg"])} for r in csv.DictReader(f)]
    return rows, rows[0]["fov"] if rows else 0.0


def cone(lat: float, lon: float, az: float, fov: float, range_m: float):
    """Polygon ring for one pose's field of view, in [lon, lat] order."""
    pts = [[lon, lat]]
    for i in range(21):
        bearing = math.radians(az - fov / 2 + i * fov / 20)
        dlat = range_m * math.cos(bearing) / 111320
        dlon = range_m * math.sin(bearing) / (111320 * math.cos(math.radians(lat)))
        pts.append([lon + dlon, lat + dlat])
    pts.append([lon, lat])
    return pts


# ── station position, shared by every camera on the Pi ────────────────────────
saved_path = base / "selected_poses.json"
saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}

first_saved = next(iter(saved.values()), {})
latlon = st.text_input(
    "Station lat, lon", placeholder="48.426801, 2.710724",
    value=(f"{first_saved['lat']}, {first_saved['lon']}" if first_saved.get("lat") else ""))
range_km = st.sidebar.number_input("Detection range on the map (km)",
                                   value=DEFAULT_RANGE_KM, step=0.5)
try:
    station_lat, station_lon = (float(v) for v in latlon.split(","))
except ValueError:
    station_lat = station_lon = None
    if latlon.strip():
        st.warning("Expected `lat, lon` — e.g. `48.426801, 2.710724`")

# ── one section per camera ────────────────────────────────────────────────────
for (rgb, hexcolor), cam_dir in zip(CAM_COLORS, cam_dirs):
    cam_ip = cam_dir.name
    rows, fov = read_calibration(cam_dir)
    images = latest_per_pose(cam_dir / "images")
    sel_key = f"sel_{cam_ip}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = {int(p.split("_")[1])
                                     for p in saved.get(cam_ip, {}).get("poses", {})}
    selected = st.session_state[sel_key]

    st.markdown(f"<span style='border-left:4px solid {hexcolor}; padding-left:8px'>"
                f"<b>{cam_ip}</b> — {len(selected)} of {len(rows)} poses, "
                f"FOV {fov:.1f}°</span>", unsafe_allow_html=True)

    # one pose in N is the usual choice: consecutive poses overlap heavily
    c1, c2, c3 = st.columns([1, 1, 4])
    every = c1.number_input("Keep 1 pose every", 1, 10, 2, key=f"every_{cam_ip}")
    if c2.button("Apply", key=f"apply_{cam_ip}", width="stretch"):
        st.session_state[sel_key] = {r["pose"] for r in rows[::int(every)]}
        st.rerun()
    if c3.button("Clear", key=f"clear_{cam_ip}"):
        st.session_state[sel_key] = set()
        st.rerun()

    cols = st.columns(COLS_PER_ROW)
    for i, row in enumerate(rows):
        with cols[i % COLS_PER_ROW]:
            path = images.get(row["pose"])
            if path:
                img = Image.open(path)
                img.thumbnail((THUMB_WIDTH, THUMB_WIDTH))
                st.image(img)
            checked = st.checkbox(f"{row['pose']} · {row['az']:.0f}°",
                                  value=row["pose"] in selected,
                                  key=f"chk_{cam_ip}_{row['pose']}")
            selected.add(row["pose"]) if checked else selected.discard(row["pose"])

    chosen = [r for r in rows if r["pose"] in selected]
    if chosen:
        gaps = blind_gaps([r["az"] for r in chosen], fov)
        worst = max(gaps)
        if worst > 0:
            st.error(f"**{worst:.1f}° blind sector** with this selection — a fire "
                     "can sit in it. Keep more poses.")
        else:
            st.success(f"Full circle covered, smallest overlap {-worst:.1f}°.")

        # ── push as presets 0..N-1 ────────────────────────────────────────────
        mapping = ", ".join(f"{r['pose']}→{i}" for i, r in enumerate(chosen))
        confirm = f"confirm_{cam_ip}"
        if not st.session_state.get(confirm):
            if st.button(f"Set presets on {cam_ip}", key=f"btn_{cam_ip}"):
                st.session_state[confirm] = True
                st.rerun()
        else:
            st.warning(f"This overwrites presets **0–{len(chosen) - 1}** on "
                       f"`{cam_ip}`, whatever the patrol uses today.  \n{mapping}")
            ok, cancel = st.columns(2)
            if ok.button("Confirm", key=f"ok_{cam_ip}", type="primary", width="stretch"):
                with st.status(f"Setting presets on {cam_ip}…", expanded=True) as status:
                    client = PyroCameraAPIClient(f"http://{pi_ip}:8081", timeout=60.0)
                    try:
                        client.stop_patrol(cam_ip)
                        client.start_stream(cam_ip)
                        time.sleep(2)
                        for new_idx, r in enumerate(chosen):
                            st.write(f"pose {r['pose']} → preset {new_idx}")
                            client.goto_preset(cam_ip, pose_id=r["pose"], speed=64)
                            time.sleep(3)
                            client.set_preset(cam_ip, idx=new_idx)
                        status.update(label=f"{len(chosen)} presets set — restart "
                                            "the patrol yourself.", state="complete")
                    except Exception as e:
                        status.update(label=f"Error: {e}", state="error")
                    finally:
                        try:
                            client.stop_stream()
                        except Exception:
                            pass
                st.session_state[confirm] = False
            if cancel.button("Cancel", key=f"no_{cam_ip}", width="stretch"):
                st.session_state[confirm] = False
                st.rerun()
    st.divider()

# ── map ───────────────────────────────────────────────────────────────────────
st.subheader("Coverage")
if station_lat is None:
    st.info("Enter the station lat, lon above to draw the cones.")
else:
    cones, markers = [], []
    for (rgb, _), cam_dir in zip(CAM_COLORS, cam_dirs):
        cam_ip = cam_dir.name
        rows, fov = read_calibration(cam_dir)
        markers.append({"pos": [station_lon, station_lat], "color": list(rgb),
                        "label": cam_ip})
        for r in rows:
            if r["pose"] in st.session_state[f"sel_{cam_ip}"]:
                cones.append({"polygon": cone(station_lat, station_lon, r["az"],
                                              fov, range_km * 1000),
                              "color": list(rgb),
                              "label": f"{cam_ip} · pose {r['pose']} · {r['az']:.0f}°"})
    st.pydeck_chart(pdk.Deck(
        initial_view_state=pdk.ViewState(latitude=station_lat, longitude=station_lon,
                                         zoom=10.5),
        layers=[
            pdk.Layer("PolygonLayer", cones, get_polygon="polygon",
                      get_fill_color="[color[0], color[1], color[2], 40]",
                      get_line_color="color", line_width_min_pixels=1, pickable=True),
            pdk.Layer("ScatterplotLayer", markers, get_position="pos",
                      get_fill_color="color", get_radius=120, pickable=True),
        ],
        tooltip={"text": "{label}"}))

# ── export ────────────────────────────────────────────────────────────────────
total = sum(len(st.session_state[f"sel_{d.name}"]) for d in cam_dirs)
if st.button(f"💾 Export {total} pose(s) → selected_poses.json",
             type="primary", disabled=total == 0 or station_lat is None):
    out = {}
    for cam_dir in cam_dirs:
        cam_ip = cam_dir.name
        rows, fov = read_calibration(cam_dir)
        picked = st.session_state[f"sel_{cam_ip}"]
        if not picked:
            continue
        out[cam_ip] = {
            "lat": station_lat, "lon": station_lon, "fov": round(fov, 2),
            # keys stay `pose_NN`: that is what the alert-API push script parses
            "poses": {f"pose_{r['pose']}": round(r["az"], 2)
                      for r in rows if r["pose"] in picked},
        }
    saved_path.write_text(json.dumps(out, indent=2))
    st.success(f"Saved {saved_path}")
