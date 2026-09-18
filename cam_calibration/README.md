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

After a `git pull`, Streamlit reloads the pages on its own; `watchdog` (in the
dependencies) makes it reload the modules they import as well. If a page ever
shows a `TypeError` or `ImportError` about a name that exists in the code,
restart the app.

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

**Recapture** — same range of poses, but the camera goes to each preset it
already has and takes a fresh image: nothing rotates by step, no preset is
written. For a new set of images on an existing sweep (light, season, a
cleaned lens) without redoing the presets. CLI: `--from-presets`.

Defaults: start pose 20, step 12.5°, 35 captures, width 1280 (HD).

The sweep first goes to the start preset, which must exist. On a camera
without presets, or to start the sweep elsewhere, aim it with the nudge
buttons and tick **Start from where the camera is now** (`--from-current` on
the CLI): the sweep starts there and stores it as the start pose.

Several PTZ cameras on the same Pi are captured **in parallel**: pick them in
the camera list, one progress column each. The API locks per camera, so they
never wait for each other. No video stream is used, a capture is a snapshot.

Same thing from the CLI:

```bash
python capture_poses.py --pi-ip 192.168.255.166 --cam <CAM_IP> --cam <CAM_IP_2> \
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
3. **Landmarks** — arrow through the poses; on one where you know a landmark,
   click it and type its azimuth (map, survey). On one where the sun is in
   frame, tick **☀️ The landmark is the sun**: its azimuth comes from the
   station position and the capture time (read from the file name), and
   **Find the sun** proposes the centre of the brightest blob, which a click
   corrects. The sun needs no map, so it is the reference to settle two map
   landmarks that disagree. Add it;
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

## Page 2 — Pose selection

Pick the poses the camera will patrol. Consecutive poses overlap heavily, so
only some of them are kept; `Keep 1 pose every N` does that in one click.

The FOV comes from `calibration.csv`, so the cones drawn on the map are the
measured ones. Coverage is checked as you select: the page states the smallest
overlap, or the size of the blind sector when the selection leaves a hole.

`Set presets` moves the camera to each selected pose and stores it as presets
`0..N-1`, **overwriting whatever the patrol uses today**. It asks for
confirmation and shows the mapping first. Nothing restarts the patrol
afterwards, do it yourself.

Export writes `captures/<pi_ip>/selected_poses.json`, keyed `pose_NN` so the
alert-API push script can read it.

Coverage on snow-valley-02, FOV 51.4°, step 12.3°:

| selection | poses | smallest overlap |
|---|---|---|
| every pose | 35 | 38.3° |
| 1 in 2 | 18 | 25.5° |
| 1 in 3 | 12 | 13.4° |
| 1 in 4 | 9 | 0.7° |

## Next steps

- Push the selected azimuths to the alert API
