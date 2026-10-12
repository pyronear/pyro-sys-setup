#!/bin/bash
set -euo pipefail

# Provision a factory-fresh Shelly Pro from a computer, without the phone app:
# join the site Wi-Fi with a static IP, update the firmware, then run
# harden_shelly.sh and setup_shelly_watchdog.sh.
#
# Site settings are read from shelly_config.env (copy
# shelly_config.env.example, never committed). watchdog.js is taken from a
# pyro-engine checkout at PYRO_ENGINE_DIR. The Wi-Fi is configured through SETUP_IP, either:
#   - the Shelly access point (default 192.168.33.1): connect this computer to
#     the open network named like ShellyPro2PM-XXXXXXXXXXXX first, or
#   - the Ethernet address: plug the Shelly into the router and set SETUP_IP to
#     its DHCP address or to shellypro4pm-<mac>.local.
# If SETUP_IP is not reachable, the Wi-Fi step is skipped and the Shelly is
# expected at SHELLY_IP.
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

: "${WIFI_SSID:?set WIFI_SSID in shelly_config.env}"
: "${WIFI_PASS:?set WIFI_PASS in shelly_config.env}"
SHELLY_IP="${SHELLY_IP:-192.168.1.97}"
NETMASK="${NETMASK:-255.255.255.0}"
GATEWAY="${GATEWAY:-192.168.1.1}"
DNS="${DNS:-$GATEWAY}"
SETUP_IP="${SETUP_IP:-192.168.33.1}"
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

d = json.load(sys.stdin)
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

sta_has_ip() {
  local status
  status=$(rpc "$SETUP_IP" WiFi.GetStatus)
  [ "$(jget status <<<"$status")" = "got ip" ] && [ "$(jget sta_ip <<<"$status")" = "$SHELLY_IP" ]
}

echo "== Wi-Fi station =="
if rpc "$SETUP_IP" Shelly.GetDeviceInfo; then
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
  echo "No Shelly at ${SETUP_IP}, assuming it is already on the site Wi-Fi"
fi

echo "== Waiting for the Shelly at ${SHELLY_IP} =="
wait_for 300 rpc "$SHELLY_IP" Shelly.GetDeviceInfo || { echo "Shelly not reachable at ${SHELLY_IP}"; exit 1; }

echo "== Firmware update =="
new=$(rpc "$SHELLY_IP" Shelly.CheckForUpdate | jget stable.version || true)
fw_is_new() { [ "$(rpc "$SHELLY_IP" Shelly.GetDeviceInfo | jget ver)" = "$new" ]; }
if [ -n "$new" ]; then
  echo "Updating to ${new}"
  rpc "$SHELLY_IP" Shelly.Update '{"stage":"stable"}'
  echo
  wait_for 600 fw_is_new || { echo "Firmware update to ${new} did not complete"; exit 1; }
else
  echo "Already up to date, or no internet access"
fi

./harden_shelly.sh
./setup_shelly_watchdog.sh
