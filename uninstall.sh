#!/usr/bin/env bash
# rpi-access uninstaller. Removes the install but leaves your saved
# WiFi credentials by default — pass --purge to wipe them too.
set -euo pipefail

NC=$'\033[0m'; BOLD=$'\033[1m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'
say()  { printf '%s==>%s %s\n' "$BOLD" "$NC" "$*"; }
ok()   { printf '%s ✓%s %s\n'  "$GRN"  "$NC" "$*"; }
warn() { printf '%s !%s %s\n'  "$YEL"  "$NC" "$*"; }
die()  { printf '%s ✗%s %s\n'  "$RED"  "$NC" "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "must be run as root"

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--purge]
  --purge   also remove /etc/rpi-access (saved networks, keys)
EOF
      exit 0 ;;
    *) warn "unknown argument: $arg" ;;
  esac
done

PREFIX="${RPI_ACCESS_PREFIX:-/opt/rpi-access}"
ETC_DIR="/etc/rpi-access"
LOG_DIR="/var/log/rpi-access"
SVC_NAME="rpi-access.service"
SVC_PATH="/etc/systemd/system/${SVC_NAME}"
AP_NAME="${RPI_ACCESS_AP_NAME:-rpi-access-AP}"

say "Stopping service"
if systemctl list-unit-files | grep -q "^${SVC_NAME}"; then
  systemctl stop "$SVC_NAME" 2>/dev/null || true
  systemctl disable "$SVC_NAME" 2>/dev/null || true
  rm -f "$SVC_PATH"
  systemctl daemon-reload
  ok "service removed"
else
  warn "service not present"
fi

say "Tearing down AP profile (if any)"
if command -v nmcli >/dev/null; then
  if nmcli -t -f NAME connection show | grep -qx "$AP_NAME"; then
    nmcli connection down id "$AP_NAME" || true
    nmcli connection delete id "$AP_NAME" || true
    ok "removed nmcli profile $AP_NAME"
  fi
fi

say "Removing payload"
rm -rf "$PREFIX"
ok "removed $PREFIX"

if [[ $PURGE -eq 1 ]]; then
  say "Purging config + credentials"
  rm -rf "$ETC_DIR" "$LOG_DIR"
  ok "removed $ETC_DIR and $LOG_DIR"
else
  warn "kept $ETC_DIR (saved WiFi creds, master key)"
  warn "use --purge to wipe them as well"
fi

cat <<EOF

$BOLD${GRN}✓ rpi-access uninstalled$NC
EOF
