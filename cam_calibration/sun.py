"""
The sun as a landmark: its azimuth at a given time needs no map, and it is
in the frame of some pose twice a day.

- sun_position(lat, lon, t): azimuth and altitude, NOAA's algorithm, within
  0.05 deg of pysolar — no dependency for one function.
- find_sun(image): a proposal for the sun's centre, the largest saturated
  blob. The user picks the image and can correct the point with a click, so
  no cleverness here: a wrong proposal costs one click.

Self-check:
    uv run python sun.py
"""

import math
from collections import deque
from datetime import datetime, timezone

import numpy as np
from PIL import Image

SATURATION = 245          # grey level: the sun's core is clipped
MIN_RADIUS_PX = 3         # below this it is noise, not a proposal


def sun_position(lat: float, lon: float, t: datetime) -> tuple[float, float]:
    """(azimuth from north clockwise, altitude) in degrees. `t` must carry a
    timezone; it is converted to UTC."""
    t = t.astimezone(timezone.utc)
    jd = t.timestamp() / 86400.0 + 2440587.5
    T = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360.0
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = ((1.914602 - T * (0.004817 + 0.000014 * T)) * math.sin(Mr)
         + (0.019993 - 0.000101 * T) * math.sin(2 * Mr) + 0.000289 * math.sin(3 * Mr))
    omega = math.radians(125.04 - 1934.136 * T)
    lam = math.radians(L0 + C - 0.00569 - 0.00478 * math.sin(omega))
    eps = math.radians(23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
                       + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2) ** 2
    L0r = math.radians(L0)
    eqt = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * e * math.sin(Mr)
                           + 4 * e * y * math.sin(Mr) * math.cos(2 * L0r)
                           - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * e * e * math.sin(2 * Mr))
    minutes = t.hour * 60 + t.minute + t.second / 60 + t.microsecond / 6e7
    ha = math.radians(((minutes + eqt + 4 * lon) % 1440) / 4 - 180)
    latr = math.radians(lat)
    zen = math.acos(math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(ha))
    a = math.degrees(math.acos(max(-1.0, min(1.0, (math.sin(latr) * math.cos(zen) - math.sin(decl))
                                                / (math.cos(latr) * math.sin(zen))))))
    az = (a + 180.0) % 360.0 if ha > 0 else (540.0 - a) % 360.0
    return az, 90.0 - math.degrees(zen)


def _blobs(mask: np.ndarray):
    """Connected components of a boolean mask: list of (ys, xs) arrays.
    Plain BFS over the true pixels — only the saturated ones, a few thousand."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        q, ys, xs = deque([(y0, x0)]), [], []
        while q:
            y, x = q.popleft()
            ys.append(y)
            xs.append(x)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        yield np.array(ys), np.array(xs)


def find_sun(image: Image.Image) -> tuple[float, float, float] | None:
    """(x, y, radius_px) of the largest saturated blob, or None."""
    grey = np.asarray(image.convert("L"))
    best = None
    for ys, xs in _blobs(grey >= SATURATION):
        r = math.sqrt(len(ys) / math.pi)
        if r >= MIN_RADIUS_PX and (best is None or r > best[2]):
            best = (float(xs.mean()), float(ys.mean()), r)
    return best


def demo() -> None:
    # ── sun position against pysolar (values computed once with it) ─────────
    lat, lon = 50.98348, 5.48977                       # East Limburg station
    for iso, az_ref, alt_ref in [("2026-09-18T05:55:06+00:00", 93.28, 5.18),
                                 ("2026-09-18T08:47:34+02:00", 103.69, 13.24),
                                 ("2026-09-18T17:30:00+00:00", 270.64, 1.92),
                                 ("2026-06-21T12:00:00+00:00", 189.95, 62.19),
                                 ("2026-12-21T10:00:00+00:00", 157.51, 12.70)]:
        az, alt = sun_position(lat, lon, datetime.fromisoformat(iso))
        assert abs(az - az_ref) < 0.1, (iso, az, az_ref)
        assert abs(alt - alt_ref) < 0.3, (iso, alt, alt_ref)

    # ── find_sun: the biggest saturated blob, even clipped by the frame top ──
    img = np.full((360, 640, 3), 190, dtype=np.uint8)
    yy, xx = np.mgrid[:360, :640]
    img[np.hypot(xx - 300, yy - 20) < 70] = 255         # the sun, blooming
    img[np.hypot(xx - 310, yy - 150) < 30] = 255        # its lens flare
    img[100:104, 500:600] = 255                         # a thin lit cloud edge
    x, y, r = find_sun(Image.fromarray(img))
    assert abs(x - 300) < 1.5 and y < 40 and r > 40, (x, y, r)
    assert find_sun(Image.fromarray(np.full((36, 64, 3), 120, dtype=np.uint8))) is None
    print("sun: all checks passed")


if __name__ == "__main__":
    demo()
