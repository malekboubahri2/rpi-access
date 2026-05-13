#!/usr/bin/env bash
# rpi-access installer.
#
# One-shot, idempotent. Safe to re-run after an upgrade — only changed
# files are rewritten and the service is restarted exactly once at the
# end.
#
# Tested on Raspberry Pi OS Bookworm (Debian 12, NetworkManager default).
#
# Usage:
#   sudo ./setup.sh                     # install
#   sudo ./setup.sh --dev               # dev mode (skip systemd enable)
#   sudo RPI_ACCESS_PREFIX=/opt ./setup.sh
set -euo pipefail

# ---------- pretty logging ---------------------------------------------------

NC=$'\033[0m'; BOLD=$'\033[1m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'
say()  { printf '%s==>%s %s\n' "$BOLD" "$NC" "$*"; }
ok()   { printf '%s ✓%s %s\n'  "$GRN"  "$NC" "$*"; }
warn() { printf '%s !%s %s\n'  "$YEL"  "$NC" "$*"; }
die()  { printf '%s ✗%s %s\n'  "$RED"  "$NC" "$*" >&2; exit 1; }

# ---------- prerequisites ----------------------------------------------------

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    die "must be run as root (try: sudo $0)"
  fi
}

# ---------- defaults / args --------------------------------------------------

DEV_MODE=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) warn "unknown argument: $arg" ;;
  esac
done

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${RPI_ACCESS_PREFIX:-/opt/rpi-access}"
ETC_DIR="/etc/rpi-access"
LOG_DIR="/var/log/rpi-access"
SVC_NAME="rpi-access.service"
SVC_PATH="/etc/systemd/system/${SVC_NAME}"

require_root

# ---------- environment checks ----------------------------------------------

say "Checking environment"
. /etc/os-release 2>/dev/null || true
if [[ "${ID:-unknown}" != "raspbian" && "${ID:-unknown}" != "debian" ]]; then
  warn "OS is ${ID:-unknown}; rpi-access is tested on Raspberry Pi OS / Debian"
fi
if [[ "${VERSION_CODENAME:-unknown}" != "bookworm" && $DEV_MODE -eq 0 ]]; then
  warn "Bookworm not detected — install may still work but is not tested"
fi
command -v nmcli >/dev/null || die "nmcli not found (apt install network-manager)"
command -v python3 >/dev/null || die "python3 not found"

PY_VER="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
ok "python ${PY_VER}, nmcli $(nmcli --version | awk '{print $4}')"

# ---------- apt deps ---------------------------------------------------------

if [[ $DEV_MODE -eq 0 ]]; then
  say "Installing apt dependencies"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3-venv python3-pip \
    network-manager \
    iproute2 iw rfkill \
    libffi-dev libssl-dev
  ok "apt deps installed"
else
  warn "--dev: skipping apt-get"
fi

# ---------- directories ------------------------------------------------------

say "Creating directories"
install -d -m 0755 "$PREFIX"
install -d -m 0755 "$ETC_DIR"
install -d -m 0750 "$LOG_DIR"
install -d -m 0755 "$PREFIX/scripts"
ok "dirs: $PREFIX, $ETC_DIR, $LOG_DIR"

# ---------- copy payload -----------------------------------------------------

say "Copying source files"
rsync -a --delete \
  --exclude=".git" --exclude=".venv" --exclude="__pycache__" \
  --exclude="*.pyc" --exclude="tests" --exclude=".pytest_cache" \
  "$REPO_ROOT"/src "$REPO_ROOT"/templates "$REPO_ROOT"/static \
  "$REPO_ROOT"/pyproject.toml "$REPO_ROOT"/requirements.txt \
  "$PREFIX/"
install -m 0755 "$REPO_ROOT"/scripts/healthcheck.sh "$PREFIX/scripts/healthcheck.sh"
install -m 0755 "$REPO_ROOT"/scripts/ap_start.sh    "$PREFIX/scripts/ap_start.sh"
install -m 0755 "$REPO_ROOT"/scripts/ap_stop.sh     "$PREFIX/scripts/ap_stop.sh"
ok "payload at $PREFIX"

# ---------- config -----------------------------------------------------------

say "Installing configuration"
if [[ -f "$ETC_DIR/rpi-access.conf" ]]; then
  warn "existing config preserved: $ETC_DIR/rpi-access.conf"
  install -m 0644 "$REPO_ROOT/config/rpi-access.conf" "$ETC_DIR/rpi-access.conf.new"
else
  install -m 0644 "$REPO_ROOT/config/rpi-access.conf" "$ETC_DIR/rpi-access.conf"
  ok "wrote $ETC_DIR/rpi-access.conf"
fi
install -m 0644 "$REPO_ROOT/config/hostapd.conf"  "$ETC_DIR/hostapd.conf"
install -m 0644 "$REPO_ROOT/config/dnsmasq.conf"  "$ETC_DIR/dnsmasq.conf"

# Master key generation — 0600 root. Fernet wants a base64-encoded 32-byte key.
KEY_FILE="$ETC_DIR/master.key"
if [[ ! -s "$KEY_FILE" ]]; then
  python3 - <<'PY' > "$KEY_FILE.tmp"
from cryptography.fernet import Fernet
import sys
sys.stdout.buffer.write(Fernet.generate_key())
PY
  install -m 0600 -o root -g root "$KEY_FILE.tmp" "$KEY_FILE"
  rm -f "$KEY_FILE.tmp"
  ok "generated $KEY_FILE"
else
  warn "master key already present — leaving it alone"
fi

# Flask secret key (separate from credential master).
SECRET_FILE="$ETC_DIR/secret.key"
if [[ ! -s "$SECRET_FILE" ]]; then
  python3 -c "import secrets;print(secrets.token_urlsafe(48))" > "$SECRET_FILE.tmp"
  install -m 0600 -o root -g root "$SECRET_FILE.tmp" "$SECRET_FILE"
  rm -f "$SECRET_FILE.tmp"
  ok "generated $SECRET_FILE"
fi

# ---------- venv -------------------------------------------------------------

say "Building Python virtualenv"
if [[ ! -d "$PREFIX/.venv" ]]; then
  python3 -m venv "$PREFIX/.venv"
fi
# shellcheck disable=SC1091
"$PREFIX/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"$PREFIX/.venv/bin/pip" install -r "$PREFIX/requirements.txt"
"$PREFIX/.venv/bin/pip" install -e "$PREFIX"
ok "venv ready at $PREFIX/.venv"

# ---------- systemd ----------------------------------------------------------

if [[ $DEV_MODE -eq 0 ]]; then
  say "Installing systemd unit"
  install -m 0644 "$REPO_ROOT/config/systemd/${SVC_NAME}" "$SVC_PATH"
  systemctl daemon-reload
  systemctl enable "$SVC_NAME"
  ok "enabled $SVC_NAME"

  say "Starting service"
  if systemctl is-active --quiet "$SVC_NAME"; then
    systemctl restart "$SVC_NAME"
  else
    systemctl start "$SVC_NAME"
  fi
  sleep 1
  systemctl --no-pager --lines=10 status "$SVC_NAME" || true
else
  warn "--dev: skipping systemd"
fi

cat <<EOF

$BOLD$GRN✓ rpi-access installed$NC

Next steps:
  - edit  $ETC_DIR/rpi-access.conf  to set ap_password / wifi_interface
  - check journalctl -u $SVC_NAME -f
  - reboot to let the orchestrator drive the boot flow from a clean slate

Portal (when in AP mode):  http://192.168.4.1
SSH in Direct Mode:        ssh user@192.168.4.1
EOF
