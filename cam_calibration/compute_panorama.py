from pathlib import Path
import re
import glob
import argparse
import json

import cv2
import numpy as np
from PIL import Image

# -------- config --------
PI_IP = "192.168.255.106"
FOV_DEG = 54.2    # camera horizontal field of view
STEP_DEG = 20.0   # degrees rotated between consecutive captures
MIN_SHIFT_PX = 350
MIN_INLIERS = 50
MAX_SIZE = 960
SKY_FRACTION = 0.0  # top fraction ignored in phase correlation — tune if sky dominates


# -------- helpers --------

def pose_num(path):
    m = re.search(r"pose_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def load_bgr(path):
    im = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(str(path))
    return im


def select_subset_by_redundancy(paths, min_shift_px=400, min_inliers=60, max_size=960):
    """Drop consecutive frames that haven't moved enough (handles skipped captures)."""
    if not paths:
        return []
    kept = [paths[0]]
    orb = cv2.ORB_create(nfeatures=4000)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    def resize_keep_aspect(img, max_w=max_size):
        h, w = img.shape[:2]
        if w <= max_w:
            return img, 1.0
        s = max_w / float(w)
        return cv2.resize(img, (max_w, int(h * s)), interpolation=cv2.INTER_AREA), s

    def keydesc(img):
        return orb.detectAndCompute(img, None)

    last_small, _ = resize_keep_aspect(load_bgr(kept[-1]))
    k_last, d_last = keydesc(last_small)

    for p in paths[1:]:
        img = load_bgr(p)
        small, _ = resize_keep_aspect(img)
        k, d = keydesc(small)
        if d is None or d_last is None or len(k) < 10 or len(k_last) < 10:
            kept.append(p)
            last_small, k_last, d_last = small, k, d
            continue

        raw = bf.knnMatch(d, d_last, k=2)
        good = [m for m, n in raw if m.distance < 0.75 * n.distance]
        if len(good) < min_inliers:
            kept.append(p)
            last_small, k_last, d_last = small, k, d
            continue

        src = np.float32([k[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([k_last[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None:
            kept.append(p)
            last_small, k_last, d_last = small, k, d
            continue

        h, w = small.shape[:2]
        center = np.array([[[w * 0.5, h * 0.5]]], dtype=np.float32)
        ctr_warp = cv2.perspectiveTransform(center, H)[0, 0]
        shift = float(np.linalg.norm(ctr_warp - center[0, 0]))
        if shift >= min_shift_px * (small.shape[1] / max_size):
            kept.append(p)
            last_small, k_last, d_last = small, k, d

    return kept



def stitch_by_phase_correlation(paths, fov_deg, step_deg, sky_fraction=SKY_FRACTION):
    """
    Build panorama using phase correlation between consecutive frames.

    Since we know each image is rotated ~step_deg from the previous one, we only
    need to refine the horizontal translation between consecutive pairs — no global
    feature matching or bundle adjustment required.
    """
    imgs = [load_bgr(p) for p in paths]
    img_h, img_w = imgs[0].shape[:2]
    nominal_shift = (step_deg / fov_deg) * img_w
    print(f"  nominal shift: {nominal_shift:.1f} px/step  (fov={fov_deg}°, step={step_deg}°, img_w={img_w})")

    # Refine shift for each consecutive pair via phase correlation
    # Strip the top SKY_FRACTION rows — sky and moving clouds corrupt FFT correlation
    sky_rows = int(img_h * sky_fraction)
    crop_h   = img_h - sky_rows
    hann     = cv2.createHanningWindow((img_w, crop_h), cv2.CV_64F)
    print(f"  skipping top {sky_rows}px (sky fraction={SKY_FRACTION})")

    raw_shifts = []
    responses  = []
    for i in range(1, len(imgs)):
        prev = cv2.cvtColor(imgs[i - 1], cv2.COLOR_BGR2GRAY).astype(np.float64)[sky_rows:]
        curr = cv2.cvtColor(imgs[i],     cv2.COLOR_BGR2GRAY).astype(np.float64)[sky_rows:]
        (dx, _dy), resp = cv2.phaseCorrelate(curr, prev, hann)
        raw_shifts.append(dx)
        responses.append(resp)

    # Estimate effective step from high-confidence pairs only.
    # A pair is "trusted" when its response is above the median AND the shift is plausible.
    median_resp = float(np.median(responses)) if responses else 0.0
    trusted = [
        dx for dx, r in zip(raw_shifts, responses)
        if r >= median_resp and nominal_shift * 0.5 < dx < nominal_shift * 2.0
    ]
    effective_shift = float(np.median(trusted)) if trusted else nominal_shift
    print(f"  effective shift: {effective_shift:.1f} px/step  "
          f"(nominal={nominal_shift:.1f}, trusted pairs={len(trusted)}/{len(raw_shifts)})")

    x_offsets = [0.0]
    for i, (dx, resp) in enumerate(zip(raw_shifts, responses), start=1):
        if abs(dx - effective_shift) > effective_shift * 0.4:
            print(f"  frame {i}: dx={dx:.1f} (resp={resp:.3f}) → clamped to effective {effective_shift:.1f}")
            dx = effective_shift
        else:
            print(f"  frame {i}: dx={dx:.1f} (resp={resp:.3f})")
        x_offsets.append(x_offsets[-1] + dx)

    # Build canvas
    pano_w = int(max(x_offsets) + img_w) + 1
    canvas = np.zeros((img_h, pano_w, 3), dtype=np.float64)
    weight = np.zeros((img_h, pano_w),    dtype=np.float64)

    # Linear feather mask (fade 15% at each side)
    fade = max(1, int(img_w * 0.15))
    mask = np.ones((img_h, img_w), dtype=np.float64)
    mask[:, :fade]  *= np.linspace(0, 1, fade)
    mask[:, -fade:] *= np.linspace(1, 0, fade)

    for img, x_off in zip(imgs, x_offsets):
        x0 = int(round(x_off))
        x1 = min(x0 + img_w, pano_w)
        w = x1 - x0
        canvas[:, x0:x1] += img[:, :w].astype(np.float64) * mask[:, :w, np.newaxis]
        weight[:, x0:x1] += mask[:, :w]

    weight = np.maximum(weight, 1e-6)
    result = (canvas / weight[:, :, np.newaxis]).clip(0, 255).astype(np.uint8)
    return result, x_offsets, img_w, effective_shift


# -------- main --------

def process_camera(folder: Path, fov_deg: float, step_deg: float, sky_fraction: float = SKY_FRACTION):
    print(f"\n=== {folder} ===")

    paths = sorted(
        [p for p in folder.glob("*.jpg") if not p.name.startswith("panorama")],
        key=pose_num,
    )
    print(f"  found {len(paths)} images")
    if not paths:
        print("  no images, skipping")
        return

    paths_subset = select_subset_by_redundancy(
        paths, min_shift_px=MIN_SHIFT_PX, min_inliers=MIN_INLIERS, max_size=MAX_SIZE
    )
    print(f"  after redundancy filter: {len(paths)} -> {len(paths_subset)} images")

    if len(paths_subset) < 2:
        print("  not enough images to stitch, skipping")
        return

    panorama, x_offsets, img_w, effective_shift = stitch_by_phase_correlation(
        paths_subset, fov_deg, step_deg, sky_fraction
    )

    pano_img = Image.fromarray(panorama[:, :, ::-1])
    out = folder.parent / "panorama_full.jpg"
    pano_img.save(out, quality=95)
    print(f"  saved -> {out}  ({pano_img.width}x{pano_img.height})")

    offsets_data = {
        "poses": {p.name: x_offsets[i] + img_w / 2 for i, p in enumerate(paths_subset)},
        "effective_shift_px": round(effective_shift, 3),
        "step_deg": step_deg,
        "fov_deg": fov_deg,
        "img_width_px": img_w,
    }
    json_out = folder.parent / "pose_offsets.json"
    json_out.write_text(json.dumps(offsets_data, indent=2))
    print(f"  saved -> {json_out}")


def main():
    parser = argparse.ArgumentParser(description="Compute panorama from PTZ capture frames")
    parser.add_argument("--pi-ip", default=PI_IP)
    parser.add_argument("--cam", default=None, help="Single camera IP (default: all)")
    parser.add_argument("--fov", type=float, default=FOV_DEG, help="Camera horizontal FOV in degrees")
    parser.add_argument("--step", type=float, default=STEP_DEG, help="Rotation step between captures in degrees")
    parser.add_argument("--sky-fraction", type=float, default=SKY_FRACTION,
                        help="Top fraction of image to skip in phase correlation (0=disabled, try 0.3 if sky dominates)")
    args = parser.parse_args()

    base = Path("captures") / args.pi_ip
    if not base.exists():
        raise SystemExit(f"Captures directory not found: {base}")

    cam_dirs = [Path(c) for c in glob.glob(str(base / "*"))]
    if args.cam:
        cam_dirs = [d for d in cam_dirs if d.name == args.cam]

    for cam_dir in sorted(cam_dirs):
        folder = cam_dir / "images"
        if folder.is_dir():
            process_camera(folder, args.fov, args.step, args.sky_fraction)


if __name__ == "__main__":
    main()
