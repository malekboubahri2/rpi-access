#!/usr/bin/env bash
# Tear down the manual AP.
set -euo pipefail

CONN_NAME="${RPI_ACCESS_AP_NAME:-rpi-access-AP}"

if ! command -v nmcli >/dev/null; then
  echo "nmcli is required" >&2; exit 1
fi

if nmcli -t -f NAME connection show | grep -qx "$CONN_NAME"; then
  nmcli connection down id "$CONN_NAME" || true
  nmcli connection delete id "$CONN_NAME" || true
  echo "AP profile '$CONN_NAME' removed." >&2
else
  echo "No AP profile named '$CONN_NAME' found." >&2
fi
