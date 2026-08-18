# Camera Azimuth Calibration

Assigns a compass azimuth to every PTZ pose of a Pyronear wildfire detection camera.
The output (`calibration.csv`) lets pyro-engine convert a captured image into a fire azimuth.

## Quick start

```bash
cd cam_calibration
uv sync                          # create venv and install deps (once)
uv run streamlit run app.py      # launch the app
```

## Overview

```
PTZ sweep (>360°)
      │  compute_panorama.py
      ▼
panorama_full.jpg + pose_offsets.json
      │  Streamlit app  (streamlit run app.py)
      ▼
calibration.csv  ←  one azimuth per pose
      │  estimate_azimuth.py
      ▼
azimuth of any new image
```

---

## Step 1 — Capture & build panorama

Run from the **Capture** page of the app, or manually:

```bash
python compute_panorama.py --pi-ip <VPN_IP> --fov 54.2 --step 20
```

The camera performs a full PTZ sweep (configured to cover >360° so the start and end overlap).
Each pose image is saved under `captures/<pi_ip>/<cam_ip>/images/pose_N.jpg`.

Phase correlation between consecutive frames measures the actual pixel shift per step.
The panorama is assembled and two files are written:

| File | Content |
|------|---------|
| `panorama_full.jpg` | Full stitched panorama |
| `pose_offsets.json` | Center-x pixel of each pose in the panorama + measured `effective_shift_px` |

---

## Capture the sweep presets, straight and tilted up

Once the sweep has saved its presets, `get_images_presets_up.py` revisits each of them
and captures two frames — one at the preset angle, one after a short tilt up — plus one
frame at every active patrol pose. The tilted frames give a second view of the horizon
line, useful when the straight frame is dominated by foreground.

```bash
cd cam_calibration
uv run python get_images_presets_up.py --pi-ip <VPN_IP>              # all cameras
uv run python get_images_presets_up.py --pi-ip <VPN_IP> --cam <CAM_IP>
uv run python get_images_presets_up.py --pi-ip <VPN_IP> --last-pose 49
```

Cameras are captured in parallel (one thread each), the patrol is stopped before the run
and left stopped afterwards. Each file name embeds the capture time, so repeated runs
never overwrite each other:

```
captures/<pi_ip>/<cam_ip>/
├── images_sweep/pose_<N>_<YYYYmmddHHMMSS>.jpg    # at the preset
├── images_up/pose_<N>_<YYYYmmddHHMMSS>.jpg       # after the tilt up
├── images_patrol/pose_<N>_<YYYYmmddHHMMSS>.jpg   # active patrol poses
└── manifest.csv                                  # image, camera, pose, kind, datetime
```

`--last-pose` defaults to the last preset implied by the sweep configuration
(`FIRST_SAVE_POSE`, `STEP_DEGREES` and `TOTAL_DEGREES` in `get_images_calibration.py`);
pass it explicitly for sites swept with a different setting. Timestamps are recorded in
Europe/Paris time.

---

## Step 2 — Calibrate azimuths (Streamlit app)

```bash
cd cam_calibration

# First time: install dependencies
uv sync

# Run the app
uv run streamlit run app.py
```

Navigate to **page 2 · Azimuth calibration**.

Three clicks are required:

### ① Overlap — start
Navigate to a pose near the **beginning** of the sweep where a distinctive landmark is visible.
Click that landmark. Its panorama-x position is recorded.

### ② Overlap — end
Navigate to a pose near the **end** of the sweep where the **same landmark** reappears (>360° overlap).
Click it again.

These two clicks give the pixel scale:
```
px_per_deg = (px_right - px_left) / 360.0
```
This is a direct geometric measurement — no FOV spec or step angle assumption needed.

### ③ Azimuth reference
Click any landmark whose **compass azimuth you know** (read from a map, compass, or survey).
Enter that azimuth in the input field.

This anchors the absolute direction:
```
az(px) = ref_az + (px - ref_px) / px_per_deg
```

The table shows the resulting azimuth for every pose. Click **Save calibration.csv**.

---

## Output: `calibration.csv`

```
pose,name,az_center,cx,inliers,rms
30,pose_30.jpg,29.9,640.0,,
31,pose_31.jpg,51.0,1145.1,,
...
```

`az_center` is the compass azimuth (0–360°) of the center of each pose image.

---

## Step 3 — Estimate azimuth of a new image

```bash
cd cam_calibration
python estimate_azimuth.py path/to/image.jpg --pi-ip <VPN_IP> --cam <CAM_IP>

# Show per-pose match details
python estimate_azimuth.py path/to/image.jpg --pi-ip <VPN_IP> --cam <CAM_IP> --verbose
```

The script:
1. Resizes the query image to calibration pose resolution
2. SIFT-matches it against every calibrated pose image
3. Picks the pose with the most RANSAC inliers
4. Refines the sub-pose horizontal offset via homography
5. Returns `az = az_center_of_best_pose + dx / px_per_deg`

The query image can be any resolution — it is automatically resized to match the calibration poses before matching.

---

## Directory layout

```
cam_calibration/
├── app.py                     # Streamlit entry point
├── compute_panorama.py        # PTZ sweep → panorama + pose_offsets.json
├── estimate_azimuth.py        # Estimate azimuth of a new image
├── get_images_presets_up.py   # Capture each sweep preset straight + tilted up
├── requirements.txt
├── pages/
│   ├── 1_Capture.py           # Streamlit page: trigger sweep, build panorama
│   └── 2_Calibration.py       # Streamlit page: 3-click calibration workflow
└── captures/
    └── <pi_ip>/
        └── <cam_ip>/
            ├── images/
            │   └── pose_N.jpg
            ├── panorama_full.jpg
            ├── pose_offsets.json
            └── calibration.csv
```

---

## Notes

- The sweep must cover **more than 360°** so the same scene appears at both ends of the panorama. This overlap is what makes the scale calibration possible without knowing camera FOV.
- Calibration images and runtime images can differ in resolution — `estimate_azimuth.py` handles the resize automatically.
- SIFT matching works across moderate lighting changes (day/overcast) but recalibration is recommended if the camera is moved or the scene changes significantly (e.g. seasonal vegetation).
