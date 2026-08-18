"""Sweep calibration core: SIFT chain + user-clicked loop closure.

The user clicks the same distant landmark in an early and a late image of the
sweep; the landmark's bearing difference spans exactly one full turn (360 deg),
which self-calibrates the focal (hence the HFOV) and yields every rotation.

Adapted from the validated pipeline in vision/sun_localisation.
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from pysolar.solar import get_altitude, get_azimuth

TZ = ZoneInfo("Europe/Paris")  # à adapter pour des sites hors métropole
TS_RE = re.compile(r"(20\d{12})")

MATCH_MAX_WIDTH = 1400
MIN_INLIERS = 30
CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))


def list_images(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("*.jpg")) + \
           sorted(p.name for p in folder.glob("*.png"))


def load_gray(fp: Path):
    img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"image illisible : {fp.name}")
    if img.shape[1] > MATCH_MAX_WIDTH:
        img = cv2.resize(img, (MATCH_MAX_WIDTH,
                               round(img.shape[0] * MATCH_MAX_WIDTH / img.shape[1])))
    return img


def match_pair(a, b, sift, matcher):
    a, b = CLAHE.apply(a), CLAHE.apply(b)
    k1, d1 = sift.detectAndCompute(a, None)
    k2, d2 = sift.detectAndCompute(b, None)
    if d1 is None or d2 is None:
        return None
    pairs = [p for p in matcher.knnMatch(d1, d2, k=2) if len(p) == 2]
    good = [m for m, n in pairs if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return None
    p1 = np.float32([k1[m.queryIdx].pt for m in good])
    p2 = np.float32([k2[m.trainIdx].pt for m in good])
    _, inl = cv2.findHomography(p1, p2, cv2.RANSAC, 3.0)
    if inl is None:
        return None
    inl = inl.ravel().astype(bool)
    if inl.sum() < MIN_INLIERS:
        return None
    return p1[inl], p2[inl]


def rays(pts, K_inv):
    h = np.hstack([pts, np.ones((len(pts), 1))])
    r = (K_inv @ h.T).T
    return r / np.linalg.norm(r, axis=1, keepdims=True)


def kabsch(r1, r2):
    H = r1.T @ r2
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    return Vt.T @ np.diag([1, 1, d]) @ U.T


def signed_pan(R):
    return math.degrees(math.atan2(R[0, 2], R[2, 2]))


def level_frame(Rs):
    axes = []
    for i in range(1, len(Rs)):
        rvec, _ = cv2.Rodrigues(Rs[i] @ Rs[i - 1].T)
        a = rvec.ravel() / (np.linalg.norm(rvec) + 1e-12)
        axes.append(a if a[1] > 0 else -a)
    y_w = np.mean(axes, 0)
    y_w /= np.linalg.norm(y_w)
    z0 = np.array([0, 0, 1.0])
    z_w = z0 - (z0 @ y_w) * y_w
    z_w /= np.linalg.norm(z_w)
    return np.stack([np.cross(y_w, z_w), y_w, z_w], -1)


def calibrate_with_click(folder: Path, images: list[str],
                         click_a: dict, click_b: dict,
                         hfov_init: float = 52.0,
                         progress=None) -> dict:
    """click_{a,b}: {"image": name, "x": 0..1, "y": 0..1} — same landmark,
    seen one full turn apart (click_a early in the sweep, click_b late)."""
    idx = {n: i for i, n in enumerate(images)}
    if click_a["image"] not in idx or click_b["image"] not in idx:
        raise RuntimeError("image cliquée inconnue")
    ia, ib = idx[click_a["image"]], idx[click_b["image"]]
    if ia >= ib:
        raise RuntimeError("le clic 'début' doit être sur une image plus tôt que le clic 'fin'")

    sift = cv2.SIFT_create(8000, contrastThreshold=0.004)
    matcher = cv2.BFMatcher()
    imgs = []
    for i, n in enumerate(images):
        imgs.append(load_gray(folder / n))
        if progress:
            progress(0.05 + 0.10 * i / len(images), f"chargement {n}")
    h, w = imgs[0].shape
    n = len(imgs)

    pair_pts = [None] * (n - 1)
    for i in range(n - 1):
        pair_pts[i] = match_pair(imgs[i], imgs[i + 1], sift, matcher)
        if progress:
            progress(0.15 + 0.75 * (i + 1) / (n - 1),
                     f"matching {images[i]} ↔ {images[i + 1]}")
    if sum(p is not None for p in pair_pts) < 3:
        raise RuntimeError("trop peu de paires matchables pour chaîner le sweep")

    def pixel(click):
        return np.array([[click["x"] * (w - 1), click["y"] * (h - 1)]])

    if progress:
        progress(0.92, "fermeture de boucle sur le point cliqué…")
    f = (w / 2) / math.tan(math.radians(hfov_init) / 2)
    warnings, pans, med = [], {}, 0.0
    for _ in range(12):
        K_inv = np.linalg.inv(np.array([[f, 0, (w - 1) / 2],
                                        [0, f, (h - 1) / 2], [0, 0, 1.0]]))
        ests = {i: kabsch(rays(p[0], K_inv), rays(p[1], K_inv))
                for i, p in enumerate(pair_pts) if p is not None}
        pans = {i: signed_pan(R) for i, R in ests.items()}
        med = float(np.median(list(pans.values())))
        if not np.isfinite(med) or abs(med) < 1e-3:
            raise RuntimeError("pas médian nul : chaîne incohérente")
        for i, p in list(pans.items()):
            k = max(1.0, round(p / med))
            if abs(p / med - k) > 0.25:
                pair_pts[i] = None
                del pans[i], ests[i]
        if len(pans) < 3:
            raise RuntimeError("trop de paires rejetées : chaîne incohérente")

        Rs = [np.eye(3)]
        rvecs = [cv2.Rodrigues(R)[0].ravel() for R in ests.values()]
        R_syn, _ = cv2.Rodrigues(np.mean(rvecs, 0))
        for i in range(n - 1):
            Rs.append(ests.get(i, R_syn) @ Rs[-1])
        M = level_frame(Rs)

        def delta(i, click):
            """Bearing of the clicked pixel relative to the optical axis."""
            r = rays(pixel(click), K_inv)[0]
            rw = M.T @ (Rs[i].T @ r)
            zw = M.T @ (Rs[i].T @ np.array([0, 0, 1.0]))
            d = math.degrees(math.atan2(rw[0], rw[2]) - math.atan2(zw[0], zw[2]))
            return (d + 180) % 360 - 180

        # cum azimuth uses -signed_pan; same landmark one turn apart:
        # (cum_b + delta_b) - (cum_a + delta_a) = 360
        span = sum(pans.get(i, med) for i in range(ia, ib))
        total = abs(-span + delta(ib, click_b) - delta(ia, click_a))
        f *= total / 360.0

    hfov = math.degrees(2 * math.atan((w / 2) / f))
    steps = [abs(p) for _, p in sorted(pans.items())]
    cum = [0.0]
    for i in range(n - 1):
        cum.append(cum[-1] - pans.get(i, med))
    interpolated = [images[i] for i in range(n - 1) if i not in pans]
    if interpolated:
        warnings.append(f"{len(interpolated)} paire(s) non matchée(s), pas interpolés "
                        f"au pas médian après : " + ", ".join(interpolated))
    return {
        "hfov": round(hfov, 3),
        "f_px": round(f, 1),
        "n_images": n,
        "step_mean": round(float(np.mean(steps)), 3),
        "step_std": round(float(np.std(steps)), 3),
        "step_median": round(float(np.median(steps)), 3),
        "steps": [round(s, 3) for s in steps],
        "span_clicked_deg": round(abs(cum[ib] - cum[ia]), 2),
        "rel_az": [round(c % 360.0, 2) for c in cum],
        "interpolated": interpolated,
        "warnings": warnings,
        # internals for the sun-anchoring step (not serializable, session only)
        "_internals": {"Rs": Rs, "M": M, "f": f, "w": w, "h": h, "images": images},
    }


def patrol_azimuths(sweep_folder: Path, internals: dict, offset: float) -> list[dict]:
    """Azimut de chaque pose de patrouille (images_patrol/ à côté du sweep).

    Chaque image de patrouille est matchée par keypoints contre toutes les
    images du sweep ; la meilleure donne sa rotation, donc son azimut absolu.
    """
    patrol_dir = sweep_folder.parent / "images_patrol"
    if not patrol_dir.is_dir():
        raise RuntimeError(f"pas de dossier images_patrol dans {sweep_folder.parent}")
    patrol_files = sorted(patrol_dir.glob("*.jpg"))
    if not patrol_files:
        raise RuntimeError("images_patrol est vide")

    images, Rs, M = internals["images"], internals["Rs"], internals["M"]
    f, w, h = internals["f"], internals["w"], internals["h"]
    K_inv = np.linalg.inv(np.array([[f, 0, (w - 1) / 2],
                                    [0, f, (h - 1) / 2], [0, 0, 1.0]]))
    sift = cv2.SIFT_create(8000, contrastThreshold=0.004)
    matcher = cv2.BFMatcher()

    def norm_gray(fp):
        img = load_gray(fp)
        if img.shape != (h, w):
            img = cv2.resize(img, (w, h))
        return img

    descs = []
    for name, R in zip(images, Rs):
        kp, d = sift.detectAndCompute(CLAHE.apply(norm_gray(sweep_folder / name)), None)
        descs.append((name, R, kp, d))

    rows = []
    for fp in patrol_files:
        try:
            pose = int(fp.stem.split("_")[1])
        except (IndexError, ValueError):
            pose = -1
        kp_p, d_p = sift.detectAndCompute(CLAHE.apply(norm_gray(fp)), None)
        best = None
        if d_p is not None:
            for name, R, kp, d in descs:
                if d is None:
                    continue
                pairs = [p for p in matcher.knnMatch(d_p, d, k=2) if len(p) == 2]
                good = [m for m, n_ in pairs if m.distance < 0.75 * n_.distance]
                if len(good) < MIN_INLIERS:
                    continue
                p1 = np.float32([kp_p[m.queryIdx].pt for m in good])
                p2 = np.float32([kp[m.trainIdx].pt for m in good])
                _, inl = cv2.findHomography(p1, p2, cv2.RANSAC, 3.0)
                if inl is None or inl.sum() < MIN_INLIERS:
                    continue
                inl = inl.ravel().astype(bool)
                R_rel = kabsch(rays(p1[inl], K_inv), rays(p2[inl], K_inv))
                if best is None or inl.sum() > best[2]:
                    best = (R_rel.T @ R, name, int(inl.sum()))
        if best is None:
            rows.append({"pose": pose, "image": fp.name, "matched": None,
                         "inliers": 0, "azimuth": None, "elevation": None})
            continue
        R_pose, matched, inliers = best
        z = M.T @ (R_pose.T @ np.array([0, 0, 1.0]))
        az = (math.degrees(math.atan2(z[0], z[2])) + offset) % 360.0
        el = math.degrees(math.asin(float(np.clip(-z[1], -1, 1))))
        rows.append({"pose": pose, "image": fp.name, "matched": matched,
                     "inliers": inliers, "azimuth": round(az, 2),
                     "elevation": round(el, 2)})
    return rows


def capture_time(fp: Path) -> datetime:
    """Timestamp du nom de fichier (pose_NN_YYYYmmddHHMMSS.jpg), sinon mtime."""
    m = TS_RE.search(fp.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
    return datetime.fromtimestamp(fp.stat().st_mtime, TZ)


def find_coords(folder: Path):
    """lat/lon auto : device_coords.json ou selected_poses.json autour du dossier.

    Le dossier est en général captures/<pi>/<cam>/images_sweep."""
    camdir = folder.parent
    pi_dir = camdir.parent
    root = pi_dir.parent
    for fp, getter in [
        (root / "device_coords.json",
         lambda d: d.get(f"{pi_dir.name}/{camdir.name}")),
        (pi_dir / "selected_poses.json",
         lambda d: d.get(camdir.name) or next(iter(d.values()), None)),
        (root.parent / "captures copy" / pi_dir.name / "selected_poses.json",
         lambda d: d.get(camdir.name) or next(iter(d.values()), None)),
    ]:
        try:
            entry = getter(json.loads(fp.read_text()))
            if entry and "lat" in entry:
                return float(entry["lat"]), float(entry["lon"])
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return None


def sun_anchor(folder: Path, internals: dict, click_sun: dict,
               lat: float, lon: float) -> dict:
    """Azimuts absolus de toutes les images depuis un clic sur le soleil.

    click_sun: {"image": name, "x": 0..1, "y": 0..1} — centre du disque solaire.
    """
    images, Rs, M = internals["images"], internals["Rs"], internals["M"]
    f, w, h = internals["f"], internals["w"], internals["h"]
    idx = {n: i for i, n in enumerate(images)}
    if click_sun["image"] not in idx:
        raise RuntimeError("image inconnue")
    i = idx[click_sun["image"]]

    fp = folder / click_sun["image"]
    dt = capture_time(fp)
    sun_az = float(get_azimuth(lat, lon, dt))
    sun_alt = float(get_altitude(lat, lon, dt))
    if sun_alt < -1:
        raise RuntimeError(f"le soleil est sous l'horizon à {dt:%H:%M} — "
                           "mauvaise heure de capture ou mauvaises coordonnées ?")

    K_inv = np.linalg.inv(np.array([[f, 0, (w - 1) / 2],
                                    [0, f, (h - 1) / 2], [0, 0, 1.0]]))
    p = np.array([[click_sun["x"] * (w - 1), click_sun["y"] * (h - 1)]])
    rw = M.T @ (Rs[i].T @ rays(p, K_inv)[0])
    az_rel = math.degrees(math.atan2(rw[0], rw[2])) % 360.0
    el_rel = math.degrees(math.asin(float(np.clip(-rw[1], -1, 1))))
    offset = (sun_az - az_rel) % 360.0

    abs_az, elevations = [], []
    for R in Rs:
        z = M.T @ (R.T @ np.array([0, 0, 1.0]))
        abs_az.append(round((math.degrees(math.atan2(z[0], z[2])) + offset) % 360.0, 2))
        elevations.append(round(math.degrees(math.asin(float(np.clip(-z[1], -1, 1)))), 2))
    return {
        "datetime": dt.isoformat(),
        "sun_az": round(sun_az, 2),
        "sun_alt": round(sun_alt, 2),
        "el_click": round(el_rel, 2),
        "el_gap": round(abs(el_rel - sun_alt), 2),
        "offset": round(offset, 3),
        "abs_az": abs_az,
        "elevations": elevations,
    }
