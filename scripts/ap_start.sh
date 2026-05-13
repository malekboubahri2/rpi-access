#!/usr/bin/env bash
# Manual AP bring-up helper.
#
# The orchestrator normally manages the AP through nmcli. This script
# exists for operators who need to bring the AP up by hand for debugging
# (e.g. when the orchestrator failed to start). Mirrors what
# `APManager.start` does in Python.
set -euo pipefail

IFACE="${1:-wlan0}"
SSID="${2:-rpi-access-MANUAL}"
GATEWAY="${3:-192.168.4.1}"
CONN_NAME="${RPI_ACCESS_AP_NAME:-rpi-access-AP}"

if ! command -v nmcli >/dev/null; then
  echo "nmcli is required" >&2; exit 1
fi

# Tear down any leftover instance.
if nmcli -t -f NAME connection show | grep -qx "$CONN_NAME"; then
  nmcli connection down id "$CONN_NAME" || true
  nmcli connection delete id "$CONN_NAME" || true
fi

nmcli connection add type wifi ifname "$IFACE" con-name "$CONN_NAME" \
  autoconnect no ssid "$SSID"

nmcli connection modify "$CONN_NAME" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel 6 \
  ipv4.method shared \
  ipv4.addresses "${GATEWAY}/24" \
  ipv6.method disabled \
  wifi-sec.key-mgmt ""   # open AP — adjust if you need WPA2

nmcli connection up id "$CONN_NAME"
echo "AP up: ssid=${SSID} gateway=${GATEWAY}" >&2
