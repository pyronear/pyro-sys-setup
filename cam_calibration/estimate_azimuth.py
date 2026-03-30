"""
Estimate the azimuth of a camera image by matching it against calibrated pose images.

For each calibrated pose, the image is matched via SIFT. The best-matching pose gives
the base azimuth; the homography refines the sub-pose offset.

Usage:
    python estimate_azimuth.py captures/192.168.255.14/192.168.1.12/images/pose_35.jpg
    python estimate_azimuth.py --pi-ip 192.168.255.14 --cam 192.168.1.12 path/to/image.jpg
"""

from pathlib import Path
import argparse

import cv2
import numpy as np
import pandas as pd

MIN_INLIERS   = 8
RANSAC_THRESH = 3.0
DEFAULT_FOV   = 54.2
MAX_SCALE_DEV = 0.15   # homography scale must be within 15% of 1
MAX_ROTATION  = 5.0    # homography rotation must be < 5°
MAX_VERT_SHIFT = 50    # vertical shift of image centre must be < 50 px


def extract_features(img):
    extractor = cv2.SIFT_create(nfeatures=8000)
    return extractor.detectAndCompute(img, None)


def match_pair(des_q, des_ref):
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 100})
    raw = matcher.knnMatch(des_q, des_ref, k=2)
    return [m for m, n in raw if m.distance < 0.70 * n.distance]


def homography_is_valid(H, img_w, img_h):
    """Return (is_valid, reason) where H looks like a plausible camera pan."""
    sx = float(np.linalg.norm(H[:2, 0]))
    sy = float(np.linalg.norm(H[:2, 1]))
    if abs(sx - 1.0) > MAX_SCALE_DEV or abs(sy - 1.0) > MAX_SCALE_DEV:
        return False, f"scale sx={sx:.2f} sy={sy:.2f}"
    angle = float(np.degrees(np.arctan2(H[1, 0], H[0, 0])))
    if abs(angle) > MAX_ROTATION:
        return False, f"rotation {angle:.1f}°"
    cx, cy = img_w / 2, img_h / 2
    mapped = cv2.perspectiveTransform(np.float32([[[cx, cy]]]), H)[0, 0]
    vert = abs(float(mapped[1]) - cy)
    if vert > MAX_VERT_SHIFT:
        return False, f"vertical shift {vert:.0f}px"
    return True, "ok"


def find_best_pose(img_path: Path, pose_dir: Path, df: pd.DataFrame, verbose: bool = False):
    """Match query image against all calibrated poses; return best match info."""
    img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(img_path)

    # Resize query to pose resolution so SIFT scale is consistent and
    # homography validity / dx computation stay correct.
    ref0 = cv2.imread(str(pose_dir / df.iloc[0]["name"]), cv2.IMREAD_COLOR)
    if ref0 is not None and img.shape[1] != ref0.shape[1]:
        pose_h, pose_w = ref0.shape[:2]
        if verbose:
            print(f"  resizing query {img.shape[1]}×{img.shape[0]} → {pose_w}×{pose_h}")
        img = cv2.resize(img, (pose_w, pose_h), interpolation=cv2.INTER_AREA)

    h, w = img.shape[:2]
    kp_q, des_q = extract_features(img)
    if des_q is None or len(kp_q) < MIN_INLIERS:
        raise ValueError("Too few features in query image")

    best = dict(inliers=0, pose_row=None, H=None, low_confidence=False)

    for _, row in df.iterrows():
        ref_path = pose_dir / row["name"]
        ref = cv2.imread(str(ref_path), cv2.IMREAD_COLOR)
        if ref is None:
            continue
        kp_r, des_r = extract_features(ref)
        if des_r is None or len(kp_r) < 4:
            continue

        good = match_pair(des_q, des_r)
        if len(good) < 4:
            if verbose:
                print(f"  {row['name']}: {len(good)} good matches (too few for homography)")
            continue

        src = np.float32([kp_q[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_r[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_THRESH)
        if H is None:
            if verbose:
                print(f"  {row['name']}: homography failed")
            continue

        n_in = int(mask.ravel().sum())
        h_ok, h_reason = homography_is_valid(H, w, h)
        valid = h_ok and n_in >= MIN_INLIERS

        if verbose:
            if valid:
                status = "✓"
            elif not h_ok:
                status = f"⚠ invalid H ({h_reason})"
            else:
                status = f"⚠ only {n_in} inliers"
            print(f"  {row['name']}: {n_in} inliers {status}")

        if n_in > best["inliers"]:
            best = dict(inliers=n_in, pose_row=row, H=H, low_confidence=not valid)

    return best


def main():
    parser = argparse.ArgumentParser(description="Estimate image azimuth from calibration")
    parser.add_argument("image", help="Path to the image file")
    parser.add_argument("--pi-ip",   default=None)
    parser.add_argument("--cam",     default=None)
    parser.add_argument("--fov",     type=float, default=DEFAULT_FOV)
    parser.add_argument("--verbose", action="store_true", help="Print per-pose match details")
    args = parser.parse_args()

    img_path = Path(args.image)

    if args.pi_ip and args.cam:
        pi_ip, cam = args.pi_ip, args.cam
    else:
        parts = img_path.parts
        try:
            idx   = parts.index("captures")
            pi_ip = parts[idx + 1]
            cam   = parts[idx + 2]
        except (ValueError, IndexError):
            raise SystemExit("Cannot infer pi_ip/cam — pass --pi-ip and --cam")

    base     = Path("captures") / pi_ip / cam
    pose_dir = base / "images"
    csv_path = base / "calibration.csv"

    if not csv_path.exists():
        raise SystemExit(f"Calibration not found: {csv_path}")

    df = pd.read_csv(csv_path)
    print(f"Image : {img_path.name}")

    best = find_best_pose(img_path, pose_dir, df, verbose=args.verbose)
    if best["pose_row"] is None:
        raise SystemExit("No pose matched at all (too few features in query image)")
    if best["low_confidence"]:
        print(f"  ⚠ Low confidence match ({best['inliers']} inliers) — result may be inaccurate")

    row = best["pose_row"]
    H   = best["H"]
    # Load and resize query to pose resolution (same as done during matching)
    img = cv2.imread(str(img_path))
    ref0 = cv2.imread(str(pose_dir / df.iloc[0]["name"]))
    if ref0 is not None and img.shape[1] != ref0.shape[1]:
        pose_h, pose_w = ref0.shape[:2]
        img = cv2.resize(img, (pose_w, pose_h), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]

    # Project query image center into the matched pose's coordinate system.
    # dx is in pose-image pixels; divide by pose pixels-per-degree.
    center_in_pose = cv2.perspectiveTransform(
        np.float32([[[w / 2, h / 2]]]), H
    )[0, 0]
    dx = float(center_in_pose[0]) - w / 2

    az_base  = float(row["az_center"])
    az_delta = dx / (w / args.fov)
    az_est   = (az_base + az_delta) % 360.0

    print(f"Best pose   : {row['name']}  ({best['inliers']} inliers)")
    print(f"Pose az     : {az_base:.1f}°")
    print(f"dx offset   : {dx:+.1f} px  ({az_delta:+.2f}°)")
    print(f"Azimuth     : {az_est:.1f}°")

    # Ground-truth comparison if the query is a calibrated pose
    gt_row = df[df["name"] == img_path.name]
    if not gt_row.empty:
        gt_az = float(gt_row.iloc[0]["az_center"])
        print(f"Ground truth: {gt_az:.1f}°   Δ={az_est - gt_az:.2f}°")


if __name__ == "__main__":
    main()
