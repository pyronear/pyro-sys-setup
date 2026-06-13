#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reolink_aio>=0.21",
#     "requests",
#     "python-dotenv",
# ]
# ///
"""First-time provisioning for factory-fresh Reolink cameras.

Replaces the manual Reolink-app steps (discover camera, create admin password,
enable HTTP/HTTPS) with an automated flow, then hands off to the existing
HTTPS/CGI configuration script (setup_reolink_cameras.py).

Run it with uv so the dependencies are fetched into a throwaway env:

    uv run provision_reolink.py                 # discover + provision + write cameras_config.json
    uv run provision_reolink.py --run-setup     # ...then run setup_reolink_cameras.py end-to-end
    uv run provision_reolink.py --ip 192.168.1.177

Per camera the flow is:
  1. discover Reolink cameras (TCP 9000 / Baichuan open on the local /24)
  2. detect state: factory-fresh (admin + empty password) vs already initialized
  3. if fresh: enable HTTP + HTTPS over Baichuan, then set the admin password
     via the CGI ModifyUser command (newPassword / oldPassword fields)
  4. verify HTTPS authenticates with the configured credentials

Then, across all cameras that came up ready:
  5. assign each a distinct target static IP from the pool in provision_config.json
     and write cameras_config.json (keyed by the camera's current/discovered IP)
  6. optionally run the standard setup script (setup_reolink_cameras.py), which
     applies OSD/AI/port settings and moves each cam to its target static IP

The whole thing is idempotent: an already-initialized camera is detected,
its ports are ensured enabled, the password step is skipped, and a camera that
already sits on a pool IP keeps it across re-runs.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

import requests
import urllib3
from dotenv import load_dotenv
from reolink_aio.api import Host
from reolink_aio.baichuan import PortType
from reolink_aio.exceptions import ApiError, CredentialsInvalidError, ReolinkError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("provision")

BAICHUAN_PORT = 9000  # TCP port the Reolink Baichuan protocol listens on
HTTPS_READY_TIMEOUT = 20  # seconds to wait for the HTTPS server after enabling it


@dataclass
class Camera:
    ip: str
    initialized: bool  # True if it already has a non-empty admin password


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def detect_local_subnet() -> ipaddress.IPv4Network:
    """Return the /24 of this host's primary outbound interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no traffic sent, just picks the route
        local_ip = s.getsockname()[0]
    finally:
        s.close()
    return ipaddress.IPv4Network(f"{local_ip}/24", strict=False)


async def _port_open(ip: str, port: int, timeout: float) -> bool:
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def discover(network: ipaddress.IPv4Network, timeout: float = 1.0) -> list[str]:
    """Scan the subnet for hosts with the Baichuan port open (Reolink cameras)."""
    log.info("Discovering Reolink cameras on %s (TCP %d)...", network, BAICHUAN_PORT)
    hosts = [str(h) for h in network.hosts()]
    results = await asyncio.gather(
        *(_port_open(ip, BAICHUAN_PORT, timeout) for ip in hosts)
    )
    found = [ip for ip, ok in zip(hosts, results) if ok]
    log.info("Found %d candidate camera(s): %s", len(found), ", ".join(found) or "none")
    return found


# --------------------------------------------------------------------------- #
# State detection + Baichuan provisioning
# --------------------------------------------------------------------------- #
async def detect_state(ip: str, admin_password: str) -> Camera | None:
    """Return a Camera with its initialized flag, or None if it isn't a Reolink cam.

    Factory-fresh cameras accept the Baichuan login with an empty password.
    Initialized cameras reject the empty password (401) but accept the
    configured admin password.
    """
    # Fresh camera: empty password is accepted.
    host = Host(ip, "admin", "")
    try:
        await host.baichuan.login()
        await _safe_logout(host)
        log.info("[%s] factory-fresh (Baichuan accepts empty password)", ip)
        return Camera(ip, initialized=False)
    except CredentialsInvalidError:
        pass  # already initialized, fall through
    except Exception as err:  # ReolinkError, or transport errors when host is down
        log.error("[%s] Baichuan connection failed: %s", ip, err)
        return None
    finally:
        await _safe_logout(host)

    # Initialized camera: confirm the configured password works.
    host = Host(ip, "admin", admin_password)
    try:
        await host.baichuan.login()
        log.info("[%s] already initialized (configured admin password accepted)", ip)
        return Camera(ip, initialized=True)
    except CredentialsInvalidError:
        log.error(
            "[%s] already initialized but the configured admin password is wrong "
            "— skipping (factory reset the camera to re-provision)", ip
        )
        return None
    except Exception as err:  # ReolinkError, or transport errors when host is down
        log.error("[%s] Baichuan connection failed: %s", ip, err)
        return None
    finally:
        await _safe_logout(host)


async def enable_http_https(ip: str, password: str) -> bool:
    """Enable the HTTP and HTTPS ports over Baichuan. Idempotent."""
    host = Host(ip, "admin", password)
    try:
        await host.baichuan.login()
        ports = await host.baichuan.get_ports()
        for name, port_type in (("http", PortType.http), ("https", PortType.https)):
            if ports.get(name, {}).get("enable") == 1:
                log.info("[%s] %s already enabled", ip, name.upper())
            else:
                await host.baichuan.set_port_enabled(port_type, True)
                log.info("[%s] %s enabled", ip, name.upper())
        return True
    except ReolinkError as err:
        log.error("[%s] failed to enable HTTP/HTTPS: %s", ip, err)
        return False
    finally:
        await _safe_logout(host)


async def _safe_logout(host: Host) -> None:
    for fn in (host.baichuan.logout, host.logout):
        try:
            await fn()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# CGI password initialization
# --------------------------------------------------------------------------- #
def _cgi_login(session: requests.Session, ip: str, user: str, password: str) -> str | None:
    """Single CGI login attempt. Returns a token, or None on failure."""
    url = f"https://{ip}/api.cgi"
    body = [{"cmd": "Login", "param": {"User": {"Version": "0", "userName": user, "password": password}}}]
    try:
        resp = session.post(url, params={"cmd": "Login"}, json=body, timeout=10)
        data = resp.json()[0]
    except (requests.RequestException, ValueError, IndexError):
        return None
    if data.get("code") == 0:
        return data["value"]["Token"]["name"]
    return None


def _wait_cgi_token(session: requests.Session, ip: str, user: str, password: str,
                    timeout: int = HTTPS_READY_TIMEOUT) -> str | None:
    """Poll CGI login until a token is returned or the timeout elapses.

    The HTTPS server takes a few seconds to start listening after the port is
    enabled over Baichuan, so the first attempts may be refused.
    """
    deadline = time.monotonic() + timeout
    while True:
        token = _cgi_login(session, ip, user, password)
        if token or time.monotonic() >= deadline:
            return token
        time.sleep(2)


def set_admin_password(ip: str, new_password: str) -> bool:
    """Set the admin password on a fresh camera via CGI ModifyUser.

    The camera must already have HTTPS enabled. The old password is empty on a
    factory-fresh camera.
    """
    session = requests.Session()
    session.verify = False

    token = _wait_cgi_token(session, ip, "admin", "")
    if not token:
        log.error("[%s] could not obtain CGI token with empty password (HTTPS not ready?)", ip)
        return False

    url = f"https://{ip}/api.cgi"
    body = [{
        "cmd": "ModifyUser",
        "action": 0,
        "param": {"User": {"userName": "admin", "newPassword": new_password, "oldPassword": ""}},
    }]
    try:
        resp = session.post(url, params={"cmd": "ModifyUser", "token": token}, json=body, timeout=10)
        data = resp.json()[0]
    except (requests.RequestException, ValueError, IndexError) as err:
        log.error("[%s] ModifyUser request failed: %s", ip, err)
        return False

    if data.get("code") != 0:
        log.error("[%s] ModifyUser rejected: %s", ip, data.get("error", data))
        return False
    log.info("[%s] admin password set", ip)
    return True


def verify_https(ip: str, user: str, password: str, timeout: int = HTTPS_READY_TIMEOUT) -> bool:
    """Confirm HTTPS authenticates with the given credentials (waits for the server)."""
    session = requests.Session()
    session.verify = False
    if _wait_cgi_token(session, ip, user, password, timeout):
        log.info("[%s] HTTPS verified with admin/<password>", ip)
        return True
    log.error("[%s] HTTPS verification failed (auth/connection not ready)", ip)
    return False


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def provision_one(ip: str, admin_password: str) -> bool:
    """Run the full provisioning flow for a single camera. Returns True if HTTPS is ready."""
    log.info("[%s] === provisioning ===", ip)
    cam = await detect_state(ip, admin_password)
    if cam is None:
        return False

    if not await enable_http_https(ip, "" if not cam.initialized else admin_password):
        return False

    if not cam.initialized:
        if not set_admin_password(ip, admin_password):
            return False
    else:
        log.info("[%s] password step skipped (already initialized)", ip)

    return verify_https(ip, "admin", admin_password)


def _ip_key(ip: str) -> tuple[int, ...]:
    return tuple(int(o) for o in ip.split("."))


def build_cam_config(ready_ips: list[str], provision_cfg: dict) -> dict:
    """Map each provisioned camera (by its current IP) to a distinct target static IP.

    A camera that already sits on one of the pool IPs keeps it (stable across
    re-runs); the remaining cameras are assigned the next free pool IPs in order.
    The output mirrors the structure setup_reolink_cameras.py expects:
    keyed by the camera's *current* IP, with LocalLink.static.ip set to its target.
    """
    pool: list[str] = list(provision_cfg["target_ips"])
    cam_type = provision_cfg.get("type", "ptz")
    mask = provision_cfg.get("mask", "255.255.255.0")
    gateway = provision_cfg.get("gateway", "192.168.1.1")

    ready_sorted = sorted(ready_ips, key=_ip_key)
    assigned: dict[str, str] = {}
    used = {ip for ip in ready_sorted if ip in pool}
    for ip in ready_sorted:  # cams already on a pool IP keep it
        if ip in pool:
            assigned[ip] = ip
    free = [p for p in pool if p not in used]
    fi = 0
    for ip in ready_sorted:  # remaining cams take the next free pool IP
        if ip in assigned:
            continue
        if fi >= len(free):
            log.error("[%s] no free target IP left in pool — leaving out of config", ip)
            continue
        assigned[ip] = free[fi]
        fi += 1

    config: dict = {}
    for current_ip, target_ip in assigned.items():
        config[current_ip] = {
            "type": cam_type,
            "LocalLink": {
                "type": "Static",
                "static": {"ip": target_ip, "mask": mask, "gateway": gateway},
            },
        }
        log.info("[%s] -> target static IP %s (type=%s)", current_ip, target_ip, cam_type)
    return config


def write_cam_config(config: dict, path: str) -> None:
    """Write cameras_config.json (overwriting any existing file)."""
    with open(path, "w") as fh:
        json.dump(config, fh, indent=4)
        fh.write("\n")
    log.info("Wrote %s (%d camera(s))", os.path.basename(path), len(config))


def run_setup_script(env_file: str, cam_config: str) -> None:
    log.info("Running standard setup script (setup_reolink_cameras.py)...")
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, os.path.join(here, "setup_reolink_cameras.py"),
           "--env_file_path", env_file, "--cam_config", cam_config]
    result = subprocess.run(cmd, cwd=here)
    if result.returncode == 0:
        log.info("Standard setup script completed")
    else:
        log.error("Standard setup script exited with code %d", result.returncode)


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv(args.env_file_path)
    admin_password = os.environ.get("CAM_PWD")
    if not admin_password:
        log.error("CAM_PWD is not set in %s", args.env_file_path)
        return 1

    if args.ip:
        targets = args.ip
    else:
        network = (
            ipaddress.IPv4Network(args.subnet, strict=False)
            if args.subnet else detect_local_subnet()
        )
        targets = await discover(network, timeout=args.scan_timeout)

    if not targets:
        log.error("No cameras to provision")
        return 1

    ready, failed = [], []
    for ip in targets:
        try:
            (ready if await provision_one(ip, admin_password) else failed).append(ip)
        except Exception as err:  # never let one camera abort the run
            log.error("[%s] unexpected error: %s", ip, err)
            failed.append(ip)

    log.info("Provisioning summary: %d ready, %d failed", len(ready), len(failed))
    if ready:
        log.info("  ready : %s", ", ".join(ready))
    if failed:
        log.info("  failed: %s", ", ".join(failed))

    if not ready:
        return 1

    # Generate cameras_config.json (keyed by current IP, each cam -> a distinct
    # target static IP from the pool) so the standard setup step can run.
    with open(args.provision_config) as fh:
        provision_cfg = json.load(fh)
    config = build_cam_config(ready, provision_cfg)
    write_cam_config(config, args.cam_config)

    if args.run_setup:
        run_setup_script(args.env_file_path, args.cam_config)
    else:
        log.info("Skipping setup (pass --run-setup to run setup_reolink_cameras.py)")

    return 0 if not failed else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Provision factory-fresh Reolink cameras (password + HTTP/HTTPS) "
                    "and hand off to setup_reolink_cameras.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--ip", nargs="+", help="Target camera IP(s); skips discovery")
    p.add_argument("--subnet", help="CIDR to scan, e.g. 192.168.1.0/24 (default: auto-detect)")
    p.add_argument("--scan-timeout", type=float, default=1.0, help="Per-host port-scan timeout (s)")
    p.add_argument("--env_file_path", default=".env", help="Env file with CAM_USER / CAM_PWD")
    p.add_argument("--provision_config", default="provision_config.json",
                   help="Intended-fleet file: target-IP pool + LocalLink template")
    p.add_argument("--cam_config", default="cameras_config.json",
                   help="Generated config consumed by the setup step (existing file is backed up)")
    p.add_argument("--run-setup", action="store_true",
                   help="After generating the config, run setup_reolink_cameras.py")
    return p.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async(parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)
