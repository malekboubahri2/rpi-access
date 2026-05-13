"""Ethernet status helper.

When the Pi is plugged into a wired LAN, we don't need WiFi onboarding —
the device is already reachable. Instead of doing nothing on the wireless
side, we put the AP into "beacon" mode: the SSID encodes the Pi's
ethernet IP so anyone in physical proximity can read the address off
the WiFi list and SSH in over the wired LAN.

This module only reads state; the orchestrator is the one that drives
AP transitions when the ethernet IP appears, disappears, or changes.
"""
from __future__ import annotations

import re
import shutil
import subprocess

from rpi_access.core.logger import get_logger

log = get_logger(__name__)

_IP_RE = re.compile(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)")


def get_ethernet_ip(iface: str) -> str | None:
    """Return the iface's IPv4 address, or None if unplugged / link-local only.

    `iface` defaults to the orchestrator's configured ethernet interface
    (typically `eth0`). 169.254/16 addresses are treated as "no IP"
    because they indicate a failed DHCP lease.
    """
    if not iface or not shutil.which("ip"):
        return None
    try:
        proc = subprocess.run(  # noqa: S603,S607
            ["ip", "-4", "addr", "show", "dev", iface],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except subprocess.SubprocessError as exc:
        log.debug("ip addr show %s failed: %s", iface, exc)
        return None
    if proc.returncode != 0:
        return None
    for match in _IP_RE.finditer(proc.stdout):
        addr = match.group(1)
        if addr.startswith("169.254."):
            continue
        return addr
    return None


def is_link_up(iface: str) -> bool:
    """Cheap link-state check, used before paying for the IP query."""
    try:
        with open(f"/sys/class/net/{iface}/operstate", encoding="ascii") as f:
            return f.read().strip() == "up"
    except OSError:
        return False
