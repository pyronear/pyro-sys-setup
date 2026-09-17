# Camera calibration

Streamlit app to define the PTZ poses a Pyronear camera must watch, and
(later) assign an azimuth to each of them.

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

**Capture loop** — from a start pose, repeat `n` times:

```
capture → save captures/<pi_ip>/<cam_ip>/images/pose_NN.jpg
        → store current position as preset NN
        → rotate by <step>°
```

Defaults: start pose 20, step 12.5°, 35 captures, width 1280 (HD).

Same thing from the CLI:

```bash
python capture_poses.py --pi-ip 192.168.255.166 --cam <CAM_IP> \
    --start-pose 20 --step 12.5 --n 35

python capture_poses.py --cam x --self-check   # logic self-check, no camera needed
```

## Next steps

- Assign an azimuth to the center of each pose
- Select the poses to keep and push them to the camera
