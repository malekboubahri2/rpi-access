#!/usr/bin/env bash
# rpi-access pre-start health check.
#
# Run as ExecStartPre by rpi-access.service. The unit fails fast if
# this script returns non-zero, which keeps systemd from masking a
# misconfigured environment under "Restart=on-failure" loops.
set -euo pipefail

log() { printf '[rpi-access-healthcheck] %s\n' "$*" >&2; }

# 1. NetworkManager present and running.
if ! command -v nmcli >/dev/null 2>&1; then
  log "nmcli not found — install network-manager and retry"
  exit 1
fi
if ! systemctl is-active --quiet NetworkManager; then
  log "NetworkManager is not active"
  exit 1
fi

# 2. Configuration file present.
CFG="${RPI_ACCESS_CONFIG:-/etc/rpi-access/rpi-access.conf}"
if [[ ! -r "$CFG" ]]; then
  log "config not readable: $CFG"
  exit 1
fi

# 3. WiFi interface exists (defaults to wlan0; allow override via env).
IFACE="${RPI_ACCESS_IFACE:-wlan0}"
if [[ ! -d "/sys/class/net/$IFACE" ]]; then
  log "wifi interface $IFACE missing"
  exit 1
fi

# 4. Master key present (encryption store needs it).
KEY="${RPI_ACCESS_KEY_FILE:-/etc/rpi-access/master.key}"
if [[ ! -s "$KEY" ]]; then
  log "master key missing or empty: $KEY"
  exit 1
fi

# 5. Log dir writable.
LOG_DIR="/var/log/rpi-access"
if [[ ! -w "$LOG_DIR" ]]; then
  log "log dir not writable: $LOG_DIR"
  exit 1
fi

log "ok"
