"""
Camera azimuth calibration.

For each PTZ pose image, matches SIFT features against the full panorama,
projects the image centre onto the panorama x-axis, and converts that pixel
position to an azimuth using a known reference point.

Usage:
    python cam_calibration.py --pi-ip 192.168.255.106 --cam 192.168.1.11 \
        --ref-azimuth 20.9 --ref-pixel 1716

Output:
    captures/<PI_IP>/<cam>/calibration.csv
"""

from pathlib import Path
import re
import glob
import argparse

import cv2
import numpy as np
import pandas as pd

# -------- config --------
PI_IP = "192.168.255.106"
FOV_DEG = 54.2          # camera horizontal field of view in degrees
MIN_INLIERS = 20
RANSAC_THRESH = 3.0


# -------- helpers --------

def pose_num(path):
    m = re.search(r"pose_(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def load_bgr(path):
    im = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(str(path))
    return im


def match_knn(desc1, desc2):
    index_params = dict(algorithm=1, trees=5)
    search_params = dict(checks=100)
    matcher = cv2.FlannBasedMatcher(index_params, search_params)
    matches = matcher.knnMatch(desc1, desc2, k=2)
    return [m for m, n in matches if m.distance < 0.75 * n.distance]


def find_homography(kp1, kp2, matches):
    if len(matches) < 12:
        return None, 0, None
    src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, RANSAC_THRESH)
    if H is None or mask is None:
        return None, 0, None
    inliers = mask.ravel().astype(bool)
    proj = cv2.perspectiveTransform(src_pts[inliers], H)
    rms = float(np.sqrt((np.linalg.norm(proj - dst_pts[inliers], axis=2) ** 2).mean()))
    return H, int(inliers.sum()), rms


def project_center(src_shape, H):
    """Return (cx, cy) of the source image centre projected onto the panorama."""
    h, w = src_shape[:2]
    center = np.float32([[[w * 0.5, h * 0.5]]])
    cx, cy = cv2.perspectiveTransform(center, H)[0, 0]
    return float(cx), float(cy)


def az_from_x(x, img_width_px, ref_azimuth, ref_pixel, fov_deg):
    px_per_deg = img_width_px / fov_deg
    return (ref_azimuth + (x - ref_pixel) / px_per_deg) % 360.0


# -------- main --------

def calibrate_camera(folder: Path, ref_azimuth: float, ref_pixel: float, fov_deg: float):
    print(f"\n=== {folder} ===")

    panorama_path = folder.parent / "panorama_full.jpg"
    if not panorama_path.exists():
        print(f"  panorama not found: {panorama_path}, skipping")
        return

    paths = sorted(
        [p for p in folder.glob("*.jpg") if not p.name.startswith("panorama")],
        key=pose_num,
    )
    print(f"  found {len(paths)} pose images")
    if not paths:
        return

    pano = load_bgr(panorama_path)
    extractor = cv2.SIFT_create(nfeatures=6000)
    kp_pano, des_pano = extractor.detectAndCompute(pano, None)
    print(f"  panorama: {pano.shape[1]}x{pano.shape[0]}px, {len(kp_pano)} keypoints")

    img_width_px = load_bgr(paths[0]).shape[1]

    rows, skipped = [], []

    for p in paths:
        src = load_bgr(p)
        kp_src, des_src = extractor.detectAndCompute(src, None)

        if des_src is None or len(kp_src) < 8:
            skipped.append((p.name, "too few features"))
            continue

        good = match_knn(des_src, des_pano)
        H, n_in, rms = find_homography(kp_src, kp_pano, good)

        if H is None or n_in < MIN_INLIERS:
            skipped.append((p.name, f"{n_in} inliers"))
            continue

        cx, cy = project_center(src.shape, H)
        az = az_from_x(cx, img_width_px, ref_azimuth, ref_pixel, fov_deg)

        rows.append(dict(pose=pose_num(p), name=p.name, cx=cx, cy=cy,
                         az_center=az, inliers=n_in, rms=rms))

    df = pd.DataFrame(rows).sort_values("pose").reset_index(drop=True)

    print(f"  valid poses: {len(df)} / {len(paths)}")
    if skipped:
        print("  skipped:")
        for name, reason in skipped:
            print(f"    {name}: {reason}")

    if df.empty:
        print("  no valid poses, cannot calibrate")
        return

    print("\n  per-pose results:")
    print(df.to_string(index=False, formatters={
        "cx": "{:.1f}".format,
        "cy": "{:.1f}".format,
        "az_center": "{:.2f}".format,
        "rms": "{:.3f}".format,
    }))

    print(f"\n  image width: {img_width_px}px  FOV: {fov_deg}°  "
          f"({fov_deg / img_width_px:.6f} deg/px)")
    print(f"  ref: pixel={ref_pixel}  azimuth={ref_azimuth}°")

    out = folder.parent / "calibration.csv"
    df.to_csv(out, index=False)
    print(f"\n  saved -> {out}")


def main():
    parser = argparse.ArgumentParser(description="Camera azimuth calibration from panorama")
    parser.add_argument("--pi-ip", default=PI_IP)
    parser.add_argument("--cam", default=None, help="Single camera IP (default: all)")
    parser.add_argument("--ref-azimuth", type=float, required=True,
                        help="Known azimuth (degrees) of the reference pixel")
    parser.add_argument("--ref-pixel", type=float, required=True,
                        help="X pixel in the panorama corresponding to ref-azimuth")
    parser.add_argument("--fov", type=float, default=FOV_DEG,
                        help=f"Camera horizontal FOV in degrees (default: {FOV_DEG})")
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
            calibrate_camera(folder, args.ref_azimuth, args.ref_pixel, args.fov)


if __name__ == "__main__":
    main()
