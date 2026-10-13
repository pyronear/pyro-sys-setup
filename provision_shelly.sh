#!/bin/bash
set -euo pipefail

# Provision a factory-fresh Shelly Pro from a computer, without the phone app:
# join the site Wi-Fi with a static IP, update the firmware, then run
# harden_shelly.sh and setup_shelly_watchdog.sh.
#
# Site settings are read from shelly_config.env (copy
# shelly_config.env.example, never committed). watchdog.js is taken from a
# pyro-engine checkout at PYRO_ENGINE_DIR. The Wi-Fi is configured through SETUP_IP, either:
#   - the Shelly access point (192.168.33.1): connect this computer to the open
#     network named like ShellyPro2PM-XXXXXXXXXXXX first, or
#   - the Ethernet address: plug the Shelly into the router, this computer
#     being on the site network.
# Leave SETUP_IP empty to find the Shelly: the access point is tried first,
# then the router subnet is scanned. If no Shelly is found, the Wi-Fi step is
# skipped and the Shelly is expected at SHELLY_IP.
#
# Usage:
#   cp shelly_config.env.example shelly_config.env   # then edit it
#   ./provision_shelly.sh

cd "$(dirname "$0")"

# Site settings, see shelly_config.env.example.
if [ -f shelly_config.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./shelly_config.env
  set +a
fi

SHELLY_IP="${SHELLY_IP:-192.168.1.97}"
NETMASK="${NETMASK:-255.255.255.0}"
GATEWAY="${GATEWAY:-192.168.1.1}"

# Without WIFI_SSID/WIFI_PASS, read the router access point over SSH: with
# ADMIN_PASSWORD from router/.env (router/provision.sh), else an SSH key or a
# password prompt.
if [ -z "${WIFI_SSID:-}" ] || [ -z "${WIFI_PASS:-}" ]; then
  echo "== Reading the Wi-Fi from the router =="
  wifi=$(
    ROUTER_IP="$GATEWAY" ROUTER_USER=root ADMIN_PASSWORD=
    # shellcheck disable=SC1091
    [ ! -f router/.env ] || . router/.env
    ssh_cmd=(ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      -o LogLevel=ERROR -o ConnectTimeout=8 -o HostKeyAlgorithms=+ssh-rsa)
    if [ -n "$ADMIN_PASSWORD" ]; then
      export SSHPASS="$ADMIN_PASSWORD"
      ssh_cmd=(sshpass -e "${ssh_cmd[@]}" -o PreferredAuthentications=password -o PubkeyAuthentication=no)
    fi
    # shellcheck disable=SC2016
    "${ssh_cmd[@]}" "${ROUTER_USER}@${ROUTER_IP}" '
      i=0
      while uci -q get "wireless.@wifi-iface[$i]" >/dev/null; do
        if [ "$(uci -q get "wireless.@wifi-iface[$i].mode")" = ap ]; then
          uci -q get "wireless.@wifi-iface[$i].ssid"
          uci -q get "wireless.@wifi-iface[$i].key"
          exit
        fi
        i=$((i + 1))
      done'
  ) || { echo "Could not read the Wi-Fi from the router, set WIFI_SSID and WIFI_PASS"; exit 1; }
  WIFI_SSID="${WIFI_SSID:-$(sed -n 1p <<<"$wifi")}"
  WIFI_PASS="${WIFI_PASS:-$(sed -n 2p <<<"$wifi")}"
fi
: "${WIFI_SSID:?set WIFI_SSID in shelly_config.env}"
: "${WIFI_PASS:?set WIFI_PASS in shelly_config.env}"
DNS="${DNS:-$GATEWAY}"
SETUP_IP="${SETUP_IP:-}"
PYRO_ENGINE_DIR="${PYRO_ENGINE_DIR:-../pyro-engine}"
export SHELLY_IP PYRO_ENGINE_DIR

# Fail before touching the Shelly rather than after hardening it.
[ -f "${PYRO_ENGINE_DIR}/watchdog/shelly/device/watchdog.js" ] \
  || { echo "watchdog.js not found in ${PYRO_ENGINE_DIR}, set PYRO_ENGINE_DIR"; exit 1; }

CURL=(curl --connect-timeout 3 --max-time 10 -fsS)

# rpc HOST METHOD [JSON_PARAMS]
rpc() {
  local body="${3:-}"
  [ -n "$body" ] || body='{}'
  "${CURL[@]}" -X POST -H "Content-Type: application/json" -d "$body" "http://$1/rpc/$2"
}

# Print a dotted field of the JSON on stdin, empty if missing.
jget() {
  python3 -c '
import json
import sys

d = json.loads(sys.stdin.read().strip() or "{}")
for k in sys.argv[1].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)
' "$1"
}

# wait_for TIMEOUT_S CMD...: retry CMD every 5 s until it succeeds.
wait_for() {
  local deadline=$((SECONDS + $1))
  shift
  until "$@" >/dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 5
  done
}

# Print the address of the only Shelly on the router subnet other than the one
# at SHELLY_IP, nothing if none, fail if several.
# ponytail: assumes a /24 around GATEWAY, set SETUP_IP on other networks.
discover() {
  python3 - "$GATEWAY" "$SHELLY_IP" <<'PY'
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

gw, skip = sys.argv[1:]
net = gw.rsplit(".", 1)[0]


def probe(ip):
    try:
        url = f"http://{ip}/rpc/Shelly.GetDeviceInfo"
        with urllib.request.urlopen(url, timeout=2) as r:
            return ip, json.load(r)["id"]
    except Exception:
        return None


with ThreadPoolExecutor(128) as ex:
    hosts = (f"{net}.{i}" for i in range(1, 255))
    found = [f for f in ex.map(probe, hosts) if f]
# The Shelly already at SHELLY_IP may also answer on its Ethernet address.
done = {dev for ip, dev in found if ip == skip}
found = [(ip, dev) for ip, dev in found if dev not in done]
for ip, dev in found:
    print(f"Found {dev} at {ip}", file=sys.stderr)
if len(found) > 1:
    sys.exit(1)
if found:
    print(found[0][0])
PY
}

sta_has_ip() {
  local status
  status=$(rpc "$SETUP_IP" WiFi.GetStatus)
  [ "$(jget status <<<"$status")" = "got ip" ] && [ "$(jget sta_ip <<<"$status")" = "$SHELLY_IP" ]
}

if [ -z "$SETUP_IP" ]; then
  echo "== Looking for the Shelly =="
  if rpc 192.168.33.1 Shelly.GetDeviceInfo >/dev/null 2>&1; then
    SETUP_IP=192.168.33.1
  else
    SETUP_IP=$(discover) || { echo "Several Shellys found, set SETUP_IP in shelly_config.env"; exit 1; }
  fi
fi

echo "== Wi-Fi station =="
if [ -n "$SETUP_IP" ] && rpc "$SETUP_IP" Shelly.GetDeviceInfo; then
  echo
  payload=$(python3 - "$WIFI_SSID" "$WIFI_PASS" "$SHELLY_IP" "$NETMASK" "$GATEWAY" "$DNS" <<'PY'
import json
import sys

ssid, pw, ip, mask, gw, dns = sys.argv[1:]
sta = {"ssid": ssid, "pass": pw, "enable": True, "ipv4mode": "static",
       "ip": ip, "netmask": mask, "gw": gw, "nameserver": dns}
print(json.dumps({"config": {"sta": sta}}))
PY
)
  rpc "$SETUP_IP" WiFi.SetConfig "$payload"
  echo
  # Check through SETUP_IP that the credentials work, before hardening turns
  # the access point off.
  echo "Waiting for the Shelly to join ${WIFI_SSID}"
  wait_for 90 sta_has_ip || { echo "Shelly did not join ${WIFI_SSID} at ${SHELLY_IP}, check SSID/password and IP"; exit 1; }
  echo ">>> Shelly is on ${WIFI_SSID}. If this computer is on the Shelly access point, reconnect it to ${WIFI_SSID} now. <<<"
else
  echo "No Shelly at ${SETUP_IP:-setup address}, assuming it is already on the site Wi-Fi"
fi

echo "== Waiting for the Shelly at ${SHELLY_IP} =="
wait_for 300 rpc "$SHELLY_IP" Shelly.GetDeviceInfo || { echo "Shelly not reachable at ${SHELLY_IP}"; exit 1; }

echo "== Firmware update =="
# The Shelly downloads the firmware itself, over IPv4 only, and a failed
# download is only reported as a notification: check it can reach the
# firmware server first rather than wait for nothing.
if ! "${CURL[@]}" --max-time 40 -X POST -d '{"url":"https://fwcdn.shelly.cloud/","timeout":30,"ssl_ca":"*"}' \
  "http://${SHELLY_IP}/rpc/HTTP.GET" >/dev/null 2>&1; then
  echo "Skipped: the Shelly has no Internet access (does the router have an IPv4 uplink?)"
else
  old=$(rpc "$SHELLY_IP" Shelly.GetDeviceInfo | jget ver)
  fw_changed() { [ "$(rpc "$SHELLY_IP" Shelly.GetDeviceInfo | jget ver)" != "$old" ]; }
  # CheckForUpdate asks the Shelly update server, it takes ~15 s.
  new=$("${CURL[@]}" --max-time 60 -X POST -d '{}' "http://${SHELLY_IP}/rpc/Shelly.CheckForUpdate" | jget stable.version || true)
  if [ -n "$new" ]; then
    echo "Updating ${old} to ${new}"
    rpc "$SHELLY_IP" Shelly.Update '{"stage":"stable"}'
    echo
    wait_for 300 fw_changed || { echo "Firmware update to ${new} did not complete"; exit 1; }
    echo "Now on $(rpc "$SHELLY_IP" Shelly.GetDeviceInfo | jget ver)"
  else
    echo "Already up to date"
  fi
fi

./harden_shelly.sh
./setup_shelly_watchdog.sh

# Hardening only warns on failed calls; the outputs powering the Pi and the
# router must really be on.
echo "== Checking outputs =="
for id in ${WATCHDOG_OUTPUTS:-0 1}; do
  on=$(rpc "$SHELLY_IP" Switch.GetStatus "{\"id\":${id}}" | jget output)
  init=$(rpc "$SHELLY_IP" Switch.GetConfig "{\"id\":${id}}" | jget initial_state)
  if [ "$on" != "True" ] || [ "$init" != "on" ]; then
    echo "Output ${id}: output=${on} initial_state=${init}, expected True/on"
    exit 1
  fi
done
echo "Shelly provisioned"
