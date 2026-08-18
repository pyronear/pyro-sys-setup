"""Push the calibrated patrol pose azimuths to the alert API.

Reads <camera_dir>/azimuts.csv (written by the calibration app), resolves the
local pose -> platform pose_id mapping through pi-manager-fr (inventory +
host_vars), then PATCHes /api/v1/poses/{id} with the azimuth rounded to 0.1 deg.

Dry-run by default: shows platform vs measured values without writing anything.

Credentials come from ALERT_API_USER / ALERT_API_PWD, or are prompted for.

Usage:
    python push_azimuths.py captures/192.168.255.26/192.168.1.11           # dry-run
    python push_azimuths.py captures/192.168.255.26/192.168.1.11 --apply   # push
"""

import argparse
import csv
import getpass
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://alertapi.pyronear.org/api/v1"
PI_MANAGER = Path.home() / "pyronear/devops/pi-manager-fr"


def api(path, token=None, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    return json.load(urllib.request.urlopen(req))


def login(user, password):
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    req = urllib.request.Request(API + "/login/creds", data=data)
    return json.load(urllib.request.urlopen(req))["access_token"]


def site_of(pi_ip):
    for hosts in ("hosts_prod", "hosts_preprod"):
        text = (PI_MANAGER / "inventory" / hosts).read_text()
        m = re.search(rf"(\S+):\n\s+ansible_host: {re.escape(pi_ip)}\b", text)
        if m:
            return m.group(1)
    raise SystemExit(f"site not found for {pi_ip} in the pi-manager inventory")


def pose_map(site, cam_ip):
    vy = (PI_MANAGER / "host_vars" / site / "vars.yml").read_text()
    cfg = json.loads(re.search(r"config_json: \|\n(.*?)(\n\S|\Z)", vy, re.S).group(1))
    cam = cfg.get(cam_ip)
    if not cam or "pose_ids" not in cam:
        raise SystemExit(f"no pose_ids for {cam_ip} in host_vars/{site}")
    return cam["name"], dict(zip(cam["poses"], cam["pose_ids"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("camera_dir", type=Path, help="captures/<pi>/<cam> holding azimuts.csv")
    ap.add_argument("--apply", action="store_true", help="actually push (dry-run otherwise)")
    ap.add_argument("--user", default=os.environ.get("ALERT_API_USER"),
                    help="alert API user (default: $ALERT_API_USER)")
    args = ap.parse_args()

    cam_dir = args.camera_dir.resolve()
    pi_ip, cam_ip = cam_dir.parent.name, cam_dir.name
    csv_path = cam_dir / "azimuts.csv"
    if not csv_path.is_file():
        raise SystemExit(f"{csv_path} not found — run the calibration app first")

    patrol = {}
    for row in csv.DictReader(open(csv_path)):
        if row["kind"] != "patrol" or not row["azimuth"]:
            continue
        pose = int(Path(row["image"]).stem.split("_")[1])
        patrol[pose] = round(float(row["azimuth"]), 1)
    if not patrol:
        raise SystemExit("no patrol row in azimuts.csv")

    site = site_of(pi_ip)
    name, mapping = pose_map(site, cam_ip)
    # never take credentials from the command line: they land in the shell history
    user = args.user or input("alert API user: ")
    password = os.environ.get("ALERT_API_PWD") or getpass.getpass("alert API password: ")
    token = login(user, password)

    print(f"{name} ({site}, {pi_ip}/{cam_ip}) — {'PUSH' if args.apply else 'dry-run'}\n")
    print(f"{'pose':>4} {'pose_id':>7} {'platform':>10} {'new':>8}")
    log_rows = []
    for pose, az in sorted(patrol.items()):
        pid = mapping.get(pose)
        if pid is None:
            print(f"{pose:>4} {'?':>7}  no pose_id in host_vars — skipped")
            continue
        current = api(f"/poses/{pid}", token).get("azimuth")
        print(f"{pose:>4} {pid:>7} {current!s:>10} {az:>8}")
        if args.apply:
            api(f"/poses/{pid}", token, method="PATCH", body={"azimuth": az})
            log_rows.append({
                "datetime": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "site": site, "camera": name, "pi_ip": pi_ip, "cam_ip": cam_ip,
                "pose": pose, "pose_id": pid, "old_azimuth": current, "new_azimuth": az,
            })
    if args.apply and log_rows:
        log = cam_dir.parent.parent / "push_log.csv"
        new_file = not log.is_file()
        with open(log, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(log_rows[0].keys()))
            if new_file:
                w.writeheader()
            w.writerows(log_rows)
        print(f"\nvalues pushed — log: {log}")
    elif not args.apply:
        print("\ndry-run — rerun with --apply to push")


if __name__ == "__main__":
    main()
