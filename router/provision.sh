#!/usr/bin/env bash
#
# Provision a Teltonika RUT router over SSH.
#
#   cp router/.env.example router/.env
#   vim router/.env
#   ./router/provision.sh
#
# Wiring: laptop -> LAN port of the router. Not the WAN port (SSH is
# firewalled off on the wan zone, and the router is its own DHCP server).
#
# Tasks: admin password, SIM PIN, and firewall rules that keep the cameras
# reachable on the LAN while denying them any route to the Internet.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

DO_INSPECT=0
DO_REBOOT=auto
DRY_RUN=0

# === Output helpers =========================================================

if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
    C_BLU=$'\033[34m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
    C_RED=; C_GRN=; C_YEL=; C_BLU=; C_DIM=; C_RST=
fi

step() { printf '\n%s=== %s ===%s\n' "$C_BLU" "$*" "$C_RST"; }
info() { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_GRN" "$C_RST" "$*"; }
warn() { printf '%s⚠ %s%s\n' "$C_YEL" "$*" "$C_RST" >&2; }
die()  { printf '%s✗ %s%s\n' "$C_RED" "$*" "$C_RST" >&2; exit 1; }

# Shell-quote a value so it can be embedded in the remote script safely.
shq() { printf "'%s'" "$(printf '%s' "${1-}" | sed "s/'/'\\\\''/g")"; }

usage() {
    cat <<'EOF'
Usage: ./router/provision.sh [options]

  --inspect       Read-only. Connect and dump firmware, SIM state, the uci
                  paths this firmware uses for the PIN, and existing firewall
                  rules. Changes nothing. Run this first on a fresh router.
  --dry-run       Show the remote script that would run, without running it.
  --no-reboot     Never reboot, even if the SIM PIN changed.
  --reboot        Always reboot at the end.
  --env PATH      Use a different env file (default: router/.env).
  -h, --help      This message.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --inspect)   DO_INSPECT=1 ;;
        --dry-run)   DRY_RUN=1 ;;
        --no-reboot) DO_REBOOT=never ;;
        --reboot)    DO_REBOOT=always ;;
        --env)       ENV_FILE="${2:-}"; shift ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "Unknown option: $1 (try --help)" ;;
    esac
    shift
done

# === Configuration ==========================================================

[ -f "$ENV_FILE" ] || die "No env file at $ENV_FILE
  cp router/.env.example router/.env  and fill it in."

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

ROUTER_USER="${ROUTER_USER:-root}"
SIM_PIN="${SIM_PIN:-}"
CAMERA_IPS="${CAMERA_IPS:-}"

[ -n "${ROUTER_IP:-}" ] || die "ROUTER_IP is not set in $ENV_FILE"
[ -n "${ADMIN_PASSWORD:-}" ] || die "ADMIN_PASSWORD is not set in $ENV_FILE"
[ -n "${DEFAULT_ADMIN_PASSWORD:-}" ] || die "DEFAULT_ADMIN_PASSWORD is not set in $ENV_FILE"

if [ "$ADMIN_PASSWORD" = "your_admin_password" ] ||
   [ "$DEFAULT_ADMIN_PASSWORD" = "password_written_on_device" ]; then
    die "$ENV_FILE still holds the placeholder values from .env.example."
fi

# RutOS rejects anything shorter than 8 characters.
if [ "${#ADMIN_PASSWORD}" -lt 8 ]; then
    die "ADMIN_PASSWORD is ${#ADMIN_PASSWORD} characters; RutOS requires at least 8."
fi

if [ -n "$SIM_PIN" ] && ! printf '%s' "$SIM_PIN" | grep -qE '^[0-9]{4,8}$'; then
    die "SIM_PIN is not 4-8 digits."
fi

CAM_LIST=""
if [ -n "$CAMERA_IPS" ]; then
    for ip in $(printf '%s' "$CAMERA_IPS" | tr ',' ' '); do
        printf '%s' "$ip" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$' ||
            die "CAMERA_IPS contains '$ip', which is not an IPv4 address.
  Expected plain comma-separated IPs, no brackets or quotes:
    CAMERA_IPS=192.168.1.11,192.168.1.12"
        CAM_LIST="$CAM_LIST $ip"
    done
    CAM_LIST="${CAM_LIST# }"
fi

# === SSH plumbing ===========================================================

SSH_BASE=(
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o GlobalKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -o ConnectTimeout=8
    -o HostKeyAlgorithms=+ssh-rsa
)
SSH_PW_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1)

AUTH_MODE=""   # key | password
AUTH_PW=""

have_sshpass() { command -v sshpass >/dev/null 2>&1; }

try_login() {
    local pw="${1-}"
    if [ -z "$pw" ]; then
        ssh "${SSH_BASE[@]}" -o BatchMode=yes "$ROUTER_USER@$ROUTER_IP" true >/dev/null 2>&1
    else
        have_sshpass || return 1
        sshpass -p "$pw" ssh "${SSH_BASE[@]}" "${SSH_PW_OPTS[@]}" \
            "$ROUTER_USER@$ROUTER_IP" true >/dev/null 2>&1
    fi
}

rsh() {
    if [ "$AUTH_MODE" = key ]; then
        ssh "${SSH_BASE[@]}" -o BatchMode=yes "$ROUTER_USER@$ROUTER_IP" "$@"
    else
        sshpass -p "$AUTH_PW" ssh "${SSH_BASE[@]}" "${SSH_PW_OPTS[@]}" \
            "$ROUTER_USER@$ROUTER_IP" "$@"
    fi
}

# Fail fast on connectivity, then work out which credential is live.
# After a first successful run the default password is gone, so ADMIN_PASSWORD
# is tried first and the factory one is the fallback.
connect() {
    step "Connecting to $ROUTER_USER@$ROUTER_IP"

    if ! ping -c 1 -W 3000 "$ROUTER_IP" >/dev/null 2>&1 &&
       ! ping -c 1 -W 3 "$ROUTER_IP" >/dev/null 2>&1; then
        warn "$ROUTER_IP does not answer ping (it may still be reachable)."
    fi

    if try_login ""; then
        AUTH_MODE=key
        ok "Authenticated with an SSH key."
        return
    fi

    have_sshpass || die "sshpass is required for password login but is not installed.
  macOS: brew install hudochenkov/sshpass/sshpass
  Debian/Ubuntu: sudo apt install sshpass"

    if try_login "$ADMIN_PASSWORD"; then
        AUTH_MODE=password; AUTH_PW="$ADMIN_PASSWORD"
        ok "Authenticated with ADMIN_PASSWORD (router already provisioned)."
        return
    fi

    if try_login "$DEFAULT_ADMIN_PASSWORD"; then
        AUTH_MODE=password; AUTH_PW="$DEFAULT_ADMIN_PASSWORD"
        ok "Authenticated with DEFAULT_ADMIN_PASSWORD (factory state)."
        return
    fi

    die "SSH authentication failed with both ADMIN_PASSWORD and DEFAULT_ADMIN_PASSWORD.
  - Is the laptop plugged into a LAN port (not WAN)?
  - Is ROUTER_IP=$ROUTER_IP correct?
  - Some RutOS builds require accepting the EULA in the web UI at
    http://$ROUTER_IP before SSH will accept a login."
}

# Pipe a generated script to the router's shell.
run_remote() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '%s--- remote script (dry run, not executed) ---%s\n' "$C_DIM" "$C_RST"
        # The prelude carries the real password and PIN; a dry run is for
        # reviewing the logic, so never print the secrets themselves.
        sed -E "s/^(NEW_PW|SIM_PIN)=.*/\1='<redacted>'/"
        printf '%s--- end ---%s\n' "$C_DIM" "$C_RST"
        return 0
    fi
    rsh 'sh -s'
}

# === Inspect ================================================================

remote_inspect() {
    cat <<'BODY'
set -u
echo "--- identity"
[ -r /etc/version ] && echo "firmware : $(cat /etc/version)"
command -v mnf_info >/dev/null 2>&1 && echo "product  : $(mnf_info --name 2>/dev/null || mnf_info -n 2>/dev/null || echo '?')"
echo "kernel   : $(uname -r)"

echo "--- SIM"
if command -v gsmctl >/dev/null 2>&1; then
    echo "AT+CPIN? : $(gsmctl -A 'AT+CPIN?' 2>&1 | tr -d '\r' | tr '\n' ' ')"
    echo "AT+CPINC?: $(gsmctl -A 'AT+CPINC?' 2>&1 | tr -d '\r' | tr '\n' ' ')"
else
    echo "gsmctl not present"
fi

echo "--- uci keys holding a PIN (this is the path provision.sh will write)"
uci show 2>/dev/null | grep -i 'pincode' || echo "  (none set yet)"

echo "--- candidate SIM sections present"
for s in simcard.sim1 'simcard.@sim[0]' network.mob1s1a1; do
    v=$(uci -q get "$s" 2>/dev/null) && echo "  $s = $v"
done

echo "--- firewall zones and their interfaces"
echo "    (every uplink must be in the wan zone for the camera rules to cover it)"
i=0
while uci -q get "firewall.@zone[$i]" >/dev/null 2>&1; do
    zn=$(uci -q get "firewall.@zone[$i].name" 2>/dev/null)
    zi=$(uci -q get "firewall.@zone[$i].network" 2>/dev/null)
    echo "  zone '$zn': ${zi:-(no networks)}"
    i=$((i + 1))
done
echo "--- interfaces with a default route (actual uplinks)"
ip route show default 2>/dev/null || route -n 2>/dev/null | grep '^0.0.0.0'
echo "--- existing camera block rules"
uci show firewall 2>/dev/null | grep 'cam_block' || echo "  (none)"

echo "--- firewall backend"
if command -v fw4 >/dev/null 2>&1; then echo "  fw4 (nftables)"; else echo "  fw3 (iptables)"; fi

echo "--- lan address"
uci -q get network.lan.ipaddr
BODY
}

# === Apply ==================================================================

remote_apply() {
    cat <<PRELUDE
NEW_PW=$(shq "$ADMIN_PASSWORD")
SIM_PIN=$(shq "$SIM_PIN")
CAM_LIST=$(shq "$CAM_LIST")
PRELUDE

    cat <<'BODY'
set -u
PIN_CHANGED=0

# --- admin password ---------------------------------------------------------
echo "> setting admin password"
if command -v chpasswd >/dev/null 2>&1 &&
   printf 'root:%s\n' "$NEW_PW" | chpasswd >/dev/null 2>&1; then
    echo "  password set (chpasswd)"
elif printf '%s\n%s\n' "$NEW_PW" "$NEW_PW" | passwd root >/dev/null 2>&1; then
    echo "  password set (passwd)"
else
    echo "  FAILED to set the admin password"
    exit 20
fi

# --- SIM PIN ----------------------------------------------------------------
if [ -n "$SIM_PIN" ]; then
    echo "> configuring SIM PIN"

    # Prefer whatever key this firmware already exposes; fall back to probing
    # the known section names across RutOS 6 / 7 layouts.
    PIN_SECTIONS=$(uci show 2>/dev/null | grep '\.pincode=' | cut -d= -f1 | sed 's/\.pincode$//')
    if [ -z "$PIN_SECTIONS" ]; then
        # RutOS 7.18 (RUT200) exposes simcard.@sim[0] and network.mob1s1a1;
        # older builds use simcard.sim1. Writing an unused key is harmless,
        # missing the live one silently loses the PIN, so set every match.
        for s in simcard.sim1 'simcard.@sim[0]' network.mob1s1a1; do
            uci -q get "$s" >/dev/null 2>&1 && PIN_SECTIONS="$PIN_SECTIONS $s"
        done
    fi

    if [ -z "$PIN_SECTIONS" ]; then
        echo "  WARNING: no SIM/mobile section found in uci; PIN not stored."
        echo "  Run ./router/provision.sh --inspect and report the output."
    else
        for s in $PIN_SECTIONS; do
            cur=$(uci -q get "$s.pincode" 2>/dev/null || echo "")
            if [ "$cur" = "$SIM_PIN" ]; then
                echo "  $s.pincode already correct"
            else
                uci set "$s.pincode=$SIM_PIN"
                PIN_CHANGED=1
                echo "  $s.pincode updated"
            fi
        done
    fi

    # Can the PIN be verified? Only if a SIM is actually in the slot.
    SIM_STATE=UNKNOWN
    PIN_TRIES=""
    if command -v gsmctl >/dev/null 2>&1; then
        cpin=$(gsmctl -A 'AT+CPIN?' 2>/dev/null | tr -d '\r')
        case "$cpin" in
            *READY*)        SIM_STATE=READY ;;
            *"SIM PUK"*)    SIM_STATE=PUK_LOCKED ;;
            *"SIM PIN"*)    SIM_STATE=PIN_REQUIRED ;;
            *"ERROR: 10"*|*"not inserted"*|*"NOT INSERTED"*) SIM_STATE=ABSENT ;;
        esac
        # +CPINC: <PIN1 tries left>,<PIN2>,<PUK1>,<PUK2>
        PIN_TRIES=$(gsmctl -A 'AT+CPINC?' 2>/dev/null | tr -d '\r' |
                    sed -n 's/.*+CPINC: *\([0-9]*\).*/\1/p' | head -1)
    fi
    echo "  SIM state: $SIM_STATE"
    [ -n "$PIN_TRIES" ] && echo "  PIN attempts remaining: $PIN_TRIES"

    case "$SIM_STATE" in
        READY)
            echo "  PIN accepted, SIM unlocked." ;;
        PIN_REQUIRED)
            echo "::WARN::SIM is inserted but still locked: the PIN was REJECTED. ${PIN_TRIES:+Only $PIN_TRIES attempt(s) remain before the SIM is PUK-locked. }Fix SIM_PIN in router/.env before rebooting the router again." ;;
        PUK_LOCKED)
            echo "::WARN::SIM is PUK-LOCKED. The PIN has already been retried too many times. Unlock it with the PUK from your operator before continuing." ;;
        ABSENT)
            echo "::WARN::No SIM detected. The PIN is stored but UNVERIFIED and will be applied on the next boot with a SIM present. If it is wrong, 3 boots will PUK-lock the SIM." ;;
        UNKNOWN)
            echo "::WARN::Could not read the SIM state, so the PIN could not be verified." ;;
    esac
    echo "::SIM_STATE::$SIM_STATE"
fi

# --- firewall: cameras reachable on LAN, no route to the Internet -----------
if [ -n "$CAM_LIST" ]; then
    echo "> blocking Internet access for cameras"

    uci show firewall 2>/dev/null | grep -q "\.name='wan'" ||
        echo "  WARNING: no firewall zone named 'wan'; rules may not match."

    # Named sections make this idempotent; clearing them first drops rules for
    # cameras that have since been removed from CAMERA_IPS.
    for s in $(uci show firewall 2>/dev/null | grep -o '^firewall\.cam_block_[0-9]*' | sort -u); do
        uci -q delete "$s"
    done

    i=0
    for ip in $CAM_LIST; do
        i=$((i + 1))
        uci set "firewall.cam_block_$i=rule"
        uci set "firewall.cam_block_$i.name=cam-no-internet-$i"
        uci set "firewall.cam_block_$i.src=lan"
        uci set "firewall.cam_block_$i.dest=wan"
        uci set "firewall.cam_block_$i.src_ip=$ip"
        uci set "firewall.cam_block_$i.proto=all"
        # REJECT rather than DROP so the camera fails fast instead of hanging.
        uci set "firewall.cam_block_$i.target=REJECT"
        uci set "firewall.cam_block_$i.enabled=1"
        echo "  $ip -> wan REJECT"
    done
    echo "  $i rule(s); LAN-to-LAN traffic is untouched (these match forwarded traffic only)"
fi

# --- persist and reload -----------------------------------------------------
echo "> committing"
uci commit
/etc/init.d/firewall reload >/dev/null 2>&1 && echo "  firewall reloaded" || echo "  firewall reload returned non-zero"

# --- report the WiFi access points (read-only; not modified here) -----------
i=0
while uci -q get "wireless.@wifi-iface[$i]" >/dev/null 2>&1; do
    if [ "$(uci -q get "wireless.@wifi-iface[$i].mode" 2>/dev/null)" = ap ]; then
        printf '::WIFI::%s\t%s\t%s\t%s\n' \
            "$(uci -q get "wireless.@wifi-iface[$i].ssid" 2>/dev/null)" \
            "$(uci -q get "wireless.@wifi-iface[$i].key" 2>/dev/null)" \
            "$(uci -q get "wireless.@wifi-iface[$i].encryption" 2>/dev/null)" \
            "$(uci -q get "wireless.@wifi-iface[$i].disabled" 2>/dev/null)"
    fi
    i=$((i + 1))
done

echo "::PIN_CHANGED::$PIN_CHANGED"
BODY
}

# === Verify =================================================================

remote_verify() {
    cat <<PRELUDE
SIM_PIN=$(shq "$SIM_PIN")
CAM_LIST=$(shq "$CAM_LIST")
PRELUDE

    cat <<'BODY'
set -u
FAIL=0

echo "> admin access"
echo "  logged in as $(id -un) — OK"

if [ -n "$SIM_PIN" ]; then
    echo "> SIM"
    uci show 2>/dev/null | grep -q '\.pincode=' && echo "  PIN stored in uci" || { echo "  PIN NOT stored"; FAIL=1; }
    if command -v gsmctl >/dev/null 2>&1; then
        cpin=$(gsmctl -A 'AT+CPIN?' 2>/dev/null | tr -d '\r')
        case "$cpin" in
            *READY*)     echo "  SIM unlocked (CPIN: READY)" ;;
            *"SIM PUK"*) echo "  SIM is PUK-LOCKED — too many wrong PIN attempts."; FAIL=1 ;;
            *"SIM PIN"*)
                tries=$(gsmctl -A 'AT+CPINC?' 2>/dev/null | tr -d '\r' |
                        sed -n 's/.*+CPINC: *\([0-9]*\).*/\1/p' | head -1)
                echo "  SIM still locked — the stored PIN was REJECTED${tries:+ ($tries attempt(s) left before PUK lock)}"
                echo "  Fix SIM_PIN in router/.env before the router reboots again."
                FAIL=1 ;;
            *)           echo "  SIM state not readable (no SIM inserted?) — PIN unverified" ;;
        esac
    fi
fi

if [ -n "$CAM_LIST" ]; then
    echo "> firewall"
    n=$(uci show firewall 2>/dev/null | grep -c "^firewall\.cam_block_[0-9]*=rule" || true)
    echo "  $n camera rule(s) in config"
    for ip in $CAM_LIST; do
        if { command -v nft >/dev/null 2>&1 && nft list ruleset 2>/dev/null | grep -q "$ip"; } ||
           { command -v iptables >/dev/null 2>&1 && iptables -S 2>/dev/null | grep -q "$ip"; }; then
            echo "  $ip present in the live ruleset"
        else
            echo "  $ip NOT found in the live ruleset"; FAIL=1
        fi
    done
fi

echo "> WAN / Internet"
if ping -c 2 -W 4 8.8.8.8 >/dev/null 2>&1; then
    echo "  router reaches the Internet"
else
    echo "  router cannot reach 8.8.8.8 (no SIM / no data plan / not registered yet)"
fi

exit $FAIL
BODY
}

report_wifi() {
    grep -q '^::WIFI::' "$APPLY_LOG" 2>/dev/null || return 0
    step "WiFi access point"
    grep '^::WIFI::' "$APPLY_LOG" | sed 's/^::WIFI:://' |
    while IFS=$'\t' read -r ssid key enc dis; do
        [ -n "$ssid" ] || continue
        info "  SSID       : $ssid"
        info "  password   : ${key:-(open network)}"
        info "  encryption : ${enc:-none}"
        if [ "${dis:-0}" = 1 ]; then info "  state      : disabled"; else info "  state      : enabled"; fi
        printf '\n  For rpi_config.env:\n'
        printf '    WIFI_SSID="%s"\n' "$ssid"
        printf '    WIFI_PASSWORD="%s"\n' "$key"
    done
}

wait_for_router() {
    local deadline=$((SECONDS + 240))
    info "Waiting for the router to come back..."
    while [ "$SECONDS" -lt "$deadline" ]; do
        if try_login "$ADMIN_PASSWORD" || try_login ""; then
            ok "Router is back."
            return 0
        fi
        sleep 5
    done
    die "Router did not come back within 240s. Check it manually at $ROUTER_IP."
}

# === Main ===================================================================

if [ "$DRY_RUN" = 0 ]; then
    connect
fi

if [ "$DO_INSPECT" = 1 ]; then
    step "Inspecting $ROUTER_IP (read-only)"
    remote_inspect | run_remote
    printf '\n%sNothing was changed.%s\n' "$C_DIM" "$C_RST"
    exit 0
fi

step "Provisioning $ROUTER_IP"
info "  admin password : will be set"
if [ -n "$SIM_PIN" ]; then
    info "  SIM PIN        : set (value hidden)"
else
    info "  SIM PIN        : not configured"
fi
info "  cameras blocked: ${CAM_LIST:-none}"

APPLY_LOG="$(mktemp)"
trap 'rm -f "$APPLY_LOG"' EXIT

if ! remote_apply | run_remote | tee "$APPLY_LOG" | sed '/^::[A-Z_]*::/d'; then
    die "Provisioning failed. The router may be partially configured; re-run to continue."
fi

if [ "$DRY_RUN" = 1 ]; then exit 0; fi

grep '^::WARN::' "$APPLY_LOG" | sed 's/^::WARN:://' | while IFS= read -r line; do
    warn "$line"
done

report_wifi

# From here on the new password is the live one.
if [ "$AUTH_MODE" = password ]; then
    AUTH_PW="$ADMIN_PASSWORD"
fi

PIN_CHANGED="$(grep '^::PIN_CHANGED::' "$APPLY_LOG" | tail -1 | cut -d: -f5 || true)"
SIM_STATE="$(grep '^::SIM_STATE::' "$APPLY_LOG" | tail -1 | cut -d: -f5 || true)"
NEED_REBOOT=0
case "$DO_REBOOT" in
    always) NEED_REBOOT=1 ;;
    never)  NEED_REBOOT=0 ;;
    auto)
        # Only worth rebooting to make the modem re-read a PIN that changed,
        # and only if there is a SIM in the slot for it to unlock.
        if [ "${PIN_CHANGED:-0}" = 1 ] && [ "${SIM_STATE:-ABSENT}" != ABSENT ]; then
            NEED_REBOOT=1
        elif [ "${PIN_CHANGED:-0}" = 1 ]; then
            info "PIN stored; skipping reboot since no SIM is inserted."
        fi ;;
esac

if [ "$NEED_REBOOT" = 1 ]; then
    step "Rebooting (the modem must re-read the SIM PIN)"
    rsh 'reboot' >/dev/null 2>&1 || true
    sleep 15
    wait_for_router
fi

step "Post-provisioning checks"
if remote_verify | run_remote; then
    printf '\n%s✓ Router provisioned.%s\n' "$C_GRN" "$C_RST"
else
    printf '\n%s⚠ Router provisioned, but some checks did not pass (see above).%s\n' "$C_YEL" "$C_RST"
    exit 1
fi
