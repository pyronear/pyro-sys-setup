# Camera calibration

Streamlit app to define the PTZ poses a Pyronear camera must watch and give
each of them a compass azimuth.

Talks to [`pyro_camera_api`](https://github.com/pyronear/pyro-engine/tree/develop/pyro_camera_api)
running on the Pi (`http://<PI_IP>:8081`).

## Run

```bash
cd cam_calibration
uv sync                          # once
uv run streamlit run app.py
```

Set the Pi IP in the sidebar.

## Page 0 — Pose capture

**Go to a pose** — enter a pose ID, move there, capture one image to check the
framing (saved under `captures/<pi_ip>/<cam_ip>/checks/`).

**Capture loop** — deletes the previous images of that camera, then from a
start pose, repeat `n` times:

```
capture → save captures/<pi_ip>/<cam_ip>/images/pose_NN_<timestamp>.jpg
        → store current position as preset NN
        → rotate by <step>°
```

A capture that still fails after 3 tries is skipped and the sweep goes on: the
calibration page just sees one longer step there.

Defaults: start pose 20, step 12.5°, 35 captures, width 1280 (HD).

Same thing from the CLI:

```bash
python capture_poses.py --pi-ip 192.168.255.166 --cam <CAM_IP> \
    --start-pose 20 --step 12.5 --n 35

python capture_poses.py --cam x --self-check   # logic self-check, no camera needed
```

## Page 1 — Pose calibration

Gives every pose the compass azimuth of its centre. Runs offline on a capture
folder, no camera needed. No panorama, and no datasheet FOV anywhere.

The camera does not turn by the angle it is asked for: `move_by_degrees` is
duration-driven, so each step carries a systematic bias (−3% measured on
snow-valley-02), jitter, and the occasional silently dropped step. So every step
is measured rather than assumed.

1. **Measured steps** — phase correlation between consecutive poses gives the
   pixel shift of each step.
2. **FOV by loop closure** — the sweep goes past 360°, so the first pose
   reappears at the end. The FOV that makes the measured angles sum to exactly
   one turn is the real one, for this camera at this zoom:

   ```
   sum(angle(dx_i, fov)) - angle(dx_close, fov) = 360     ->  one unknown
   ```

   The closing pose is picked as the one still correlating best with the first —
   strongest overlap. Neighbouring closing poses are fitted too and must agree.
3. **Landmarks** — click a landmark of known azimuth (map, survey) and add it;
   they are kept in `captures/<pi_ip>/<cam_ip>/landmarks.json`. One landmark
   fixes the absolute direction of the whole sweep. Two or three, far apart in
   azimuth, check each other: each one votes for the sweep offset, the median
   wins, and a landmark whose residual exceeds 0.5° is misread on the map or
   clicked on the wrong thing — remove it with its 🗑 button.

Azimuths are the **cumulative sum** of the measured angles, so a dropped or long
step stays local instead of shifting every pose after it. The table flags weak
correlations, outlier steps, and any blind sector between consecutive poses.

Export → `captures/<pi_ip>/<cam_ip>/calibration.csv`.

### The band, and why it matters

Correlation only looks at a horizontal band of the frame, `0.55–0.92` of the
height by default, adjustable on the page. Both ends are deliberate:

- **the sky is worse than useless** — clouds move between two captures, and they
  cover most of the frame;
- **the bottom holds the mast or roof the camera sits on** — identical in every
  pose, so it correlates perfectly at zero shift and hides the real rotation.

On snow-valley-02 the full frame reported step 24→25 as *exactly zero* — a
plausible-looking dropped step. The two frames show plainly different views; the
mount in the bottom-left corner had won the correlation. Cropped to the ground
band it reads 12.3°, in line with its neighbours.

So a `🛑 no rotation` flag means *go look at the two frames*, not "the camera
skipped a step". The fit itself is insensitive to the exact band: 51.2–51.45°
across every band tried.

### Measured on snow-valley-02 (35 poses, 12.5° commanded)

| quantity | value |
|---|---|
| fitted FOV | **51.4°** (datasheet says 54.2) |
| mean step | **12.32°** for 12.5 commanded, −1.4% |
| step spread | 11.50 – 13.10° |
| span over 29 steps | 357.25° |

The step is not constant: ±6% around a mean that is itself 1.4% short. That is
why azimuths are a cumulative sum of measured angles rather than `i × step`.

```bash
uv run python pose_azimuth.py   # self-check, incl. the full pipeline on rendered frames
uv run python pixel_shift.py    # click-based cross-check helpers
```

## Next steps

- Select the poses to keep and push them to the camera as presets
