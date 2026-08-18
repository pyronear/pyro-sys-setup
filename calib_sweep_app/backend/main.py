"""API FastAPI de calibration de sweep.

Étapes servies au front React :
  1. GET  /api/scan?path=…           — liste les images du dossier
  2. POST /api/calibrate             — chaîne SIFT + fermeture sur les 2 clics
  3. POST /api/anchor                — clic soleil → azimuts absolus
     GET  /api/image?path=&name=&w=  — sert une image (redimensionnée)
     GET  /api/coords?path=…         — lat/lon auto du site si trouvables

Run:
    cd calib_sweep_app/backend && uvicorn main:app --port 8000
"""

import threading
import uuid
from io import BytesIO
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import (calibrate_with_click, capture_time, find_coords,  # noqa: E402
                  list_images, patrol_azimuths, sun_anchor)

app = FastAPI(title="Calibration sweep")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

JOBS: dict[str, dict] = {}      # job_id -> {"folder", "images", "internals", "result"}
LOCK = threading.Lock()         # un seul calcul SIFT à la fois


class Click(BaseModel):
    image: str
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class CalibrateBody(BaseModel):
    path: str
    click_a: Click
    click_b: Click
    hfov_init: float = Field(default=52.0, gt=20.0, lt=120.0)


class AnchorBody(BaseModel):
    job: str
    click_sun: Click
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


def checked_folder(path: str) -> Path:
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise HTTPException(400, f"dossier introuvable : {folder}")
    return folder


@app.get("/api/scan")
def scan(path: str):
    folder = checked_folder(path)
    images = list_images(folder)
    if len(images) < 4:
        raise HTTPException(400, f"seulement {len(images)} image(s) — il en faut au moins 4")
    coords = find_coords(folder)
    return {"folder": str(folder), "images": images,
            "times": {n: capture_time(folder / n).isoformat() for n in images},
            "coords": {"lat": coords[0], "lon": coords[1]} if coords else None}


@app.get("/api/image")
def image(path: str, name: str, w: int = 0):
    folder = checked_folder(path)
    fp = (folder / name).resolve()
    if not fp.is_relative_to(folder.resolve()) or fp.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(404, "image introuvable")
    if not fp.is_file():
        raise HTTPException(404, "image introuvable")
    if not w:
        return Response(fp.read_bytes(), media_type="image/jpeg")
    img = cv2.imread(str(fp))
    if img is None:
        raise HTTPException(500, "image illisible")
    if 0 < w < img.shape[1]:
        img = cv2.resize(img, (w, round(img.shape[0] * w / img.shape[1])))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg")


@app.post("/api/calibrate")
def calibrate(body: CalibrateBody):
    folder = checked_folder(body.path)
    images = list_images(folder)
    try:
        with LOCK:
            res = calibrate_with_click(folder, images,
                                       body.click_a.model_dump(),
                                       body.click_b.model_dump(),
                                       hfov_init=body.hfov_init)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    internals = res.pop("_internals")
    job = uuid.uuid4().hex[:8]
    JOBS[job] = {"folder": folder, "internals": internals}
    return {"job": job, **res}


@app.post("/api/anchor")
def anchor(body: AnchorBody):
    j = JOBS.get(body.job)
    if j is None:
        raise HTTPException(404, "calibration inconnue — relance l'étape 3")
    try:
        res = sun_anchor(j["folder"], j["internals"], body.click_sun.model_dump(),
                         body.lat, body.lon)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    j["offset"] = res["offset"]
    res["images"] = j["internals"]["images"]
    j["sweep_rows"] = [
        {"kind": "sweep", "image": n, "azimuth": a, "elevation": e}
        for n, a, e in zip(res["images"], res["abs_az"], res["elevations"])
    ]
    save_csv(j)
    res["saved_to"] = str(j["folder"].parent / "azimuts.csv")
    return res


def save_csv(j: dict) -> None:
    """azimuts.csv dans le dossier caméra, réécrit à chaque calcul."""
    import csv
    out = j["folder"].parent / "azimuts.csv"
    rows = j.get("sweep_rows", []) + j.get("patrol_rows", [])
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "image", "azimuth", "elevation"])
        w.writeheader()
        w.writerows(rows)


class PatrolBody(BaseModel):
    job: str


@app.post("/api/patrol")
def patrol(body: PatrolBody):
    j = JOBS.get(body.job)
    if j is None:
        raise HTTPException(404, "calibration inconnue — relance l'étape 3")
    if "offset" not in j:
        raise HTTPException(422, "ancrage soleil manquant — fais l'étape 4 d'abord")
    try:
        with LOCK:
            rows = patrol_azimuths(j["folder"], j["internals"], j["offset"])
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    j["patrol_rows"] = [
        {"kind": "patrol", "image": r["image"], "azimuth": r["azimuth"],
         "elevation": r["elevation"]}
        for r in rows if r["azimuth"] is not None
    ]
    save_csv(j)
    return {"rows": rows, "saved_to": str(j["folder"].parent / "azimuts.csv")}


@app.post("/api/save")
def save(body: PatrolBody):
    j = JOBS.get(body.job)
    if j is None or "sweep_rows" not in j:
        raise HTTPException(422, "rien à sauvegarder — fais l'étape 4 d'abord")
    save_csv(j)
    return {"saved_to": str(j["folder"].parent / "azimuts.csv")}


# En production : sert le build React s'il existe (frontend/dist)
dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="front")
