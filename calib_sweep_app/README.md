# Calibration sweep — React front + FastAPI API

Calibrates a camera from a 360° sweep: HFOV, real per-step angles, absolute
azimuths (anchored on the sun) and the azimuths of the patrol poses.

Local tool: the API reads image folders by path and allows any origin, so run it
on the operator machine only — do not expose port 8000.

## Run (dev)

Terminal 1 — API on port 8000, using the `cam_calibration` venv:

```bash
cd calib_sweep_app/backend
../../cam_calibration/.venv/bin/python -m uvicorn main:app --port 8000
```

Terminal 2 — front on port 5173, proxies `/api` to 8000:

```bash
cd calib_sweep_app/frontend
npm install        # first time only
npm run dev
```

→ open **http://localhost:5173**

## Run (single command, no hot reload)

```bash
cd calib_sweep_app/frontend && npm run build
cd ../backend && ../../cam_calibration/.venv/bin/python -m uvicorn main:app --port 8000
```

→ open **http://localhost:8000** (FastAPI serves the React build)

## Dependencies

- Python: the `cam_calibration/.venv` ones plus `fastapi uvicorn pysolar`
  (`uv pip install fastapi uvicorn pysolar --python cam_calibration/.venv/bin/python`)
- Node ≥ 18 for the front.

## Usage

1. **Folder**: path to an `images_sweep/` directory
   (e.g. `cam_calibration/captures/<pi>/<cam>/images_sweep`), as produced by
   `cam_calibration/get_images_presets_up.py`.
2. **360° closure**: click the **same distant landmark** in one image from the
   start and one from the end of the sweep — the sweep overshoots 360°, so the
   end sees the scene of the start again. Navigate with ◀ ▶.
3. **Compute**: self-calibrated HFOV, real per-step angles, relative azimuths
   (about 1 min of matching).
4. **Sun**: find the image showing the sun and click the center of the disc.
   lat/lon are pre-filled when the site is known (`device_coords.json` /
   `selected_poses.json`), otherwise use the `48.478, 2.424` format. Guard rail:
   an elevation gap larger than 3° between the click and the computed sun is
   reported.
5. **Patrol poses**: matches `images_patrol/` against the sweep to get the
   azimuth of each pose.

Results are written to `<camera folder>/azimuts.csv` (columns
`kind,image,azimuth,elevation`, sweep + patrol rows, rewritten on each
recompute), and can also be downloaded from the browser.

## Push the azimuths to the platform

```bash
export ALERT_API_USER=<user>          # password is prompted, or set ALERT_API_PWD
python push_azimuths.py cam_calibration/captures/<pi>/<cam>            # dry-run
python push_azimuths.py cam_calibration/captures/<pi>/<cam> --apply    # push
```

Reads `azimuts.csv`, resolves each local pose to its platform `pose_id` through
the `pi-manager-fr` inventory and host_vars, then PATCHes the azimuth. Every
applied push is appended to `push_log.csv`.
