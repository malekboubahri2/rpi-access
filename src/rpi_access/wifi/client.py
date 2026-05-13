"""Client-mode connection manager.

Strategy:

1. If an `nmcli` connection profile for the SSID already exists, just
   `connection up` it. This lets us preserve user-edited settings on
   re-onboarding.
2. Otherwise create a new profile with `device wifi connect`. nmcli will
   handle key-mgmt detection for us.
3. After `up`, poll `ip -4 addr show` until we have a non-link-local IP
   or hit the timeout.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time

from rpi_access.core.config import NetworkConfig
from rpi_access.core.exceptions import ConnectError, WifiError
from rpi_access.core.logger import get_logger
from rpi_access.wifi._nmcli import run as nmcli_run

log = get_logger(__name__)

_IP_RE = re.compile(r"inet\s+(\d+\.\d+\.\d+\.\d+)/")


class WifiClient:
    def __init__(self, cfg: NetworkConfig, *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run

    def connect(self, ssid: str, psk: str | None, *, timeout: float = 25.0) -> str:
        """Bring the client up on `ssid`. Returns its IPv4 address."""
        log.info("connecting to ssid=%s", ssid)
        if self._profile_exists(ssid):
            self._activate_profile(ssid, timeout=timeout)
        else:
            self._create_and_activate(ssid, psk, timeout=timeout)

        ip = self._wait_for_ip(timeout=timeout)
        if not ip:
            self._teardown_profile(ssid)
            raise ConnectError(f"connected to {ssid} but no IP after {timeout}s")
        log.info("connected ssid=%s ip=%s", ssid, ip)
        return ip

    def is_connected(self) -> bool:
        """Return True if the WiFi interface currently has an upstream link."""
        try:
            res = nmcli_run(
                ["-t", "-f", "DEVICE,STATE", "device"],
                timeout=5,
                dry_run=self.dry_run,
                check=False,
            )
        except WifiError:
            return False
        if self.dry_run:
            return True
        for line in res.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == self.cfg.wifi_interface:
                return parts[1] == "connected"
        return False

    # ----- internals --------------------------------------------------------------

    def _profile_exists(self, ssid: str) -> bool:
        try:
            res = nmcli_run(
                ["-t", "-f", "NAME", "connection", "show"],
                timeout=5,
                dry_run=self.dry_run,
                check=False,
            )
        except WifiError:
            return False
        if self.dry_run:
            return False
        names = {line.strip() for line in res.stdout.splitlines() if line.strip()}
        return ssid in names

    def _activate_profile(self, ssid: str, *, timeout: float) -> None:
        try:
            nmcli_run(
                ["connection", "up", "id", ssid, "ifname", self.cfg.wifi_interface],
                timeout=timeout,
                dry_run=self.dry_run,
            )
        except WifiError as exc:
            raise ConnectError(f"activate existing profile failed: {exc}") from exc

    def _create_and_activate(self, ssid: str, psk: str | None, *, timeout: float) -> None:
        args = ["device", "wifi", "connect", ssid, "ifname", self.cfg.wifi_interface]
        redact_index: int | None = None
        if psk:
            # `... password <psk>`
            args.extend(["password", psk])
            # 0=device,1=wifi,2=connect,3=ssid,4=ifname,5=iface,6=password,7=psk
            redact_index = 7
        try:
            nmcli_run(args, timeout=timeout, redact_index=redact_index, dry_run=self.dry_run)
        except WifiError as exc:
            raise ConnectError(f"nmcli connect failed: {exc}") from exc

    def _wait_for_ip(self, *, timeout: float) -> str | None:
        if self.dry_run:
            return "192.0.2.10"
        if not shutil.which("ip"):
            log.warning("`ip` not on PATH — cannot verify IP acquisition")
            return "0.0.0.0"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                proc = subprocess.run(  # noqa: S603,S607
                    ["ip", "-4", "addr", "show", self.cfg.wifi_interface],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except subprocess.SubprocessError:
                proc = None
            if proc and proc.returncode == 0:
                m = _IP_RE.search(proc.stdout)
                if m:
                    ip = m.group(1)
                    # Skip link-local 169.254.x.x — that's a DHCP failure.
                    if not ip.startswith("169.254."):
                        return ip
            time.sleep(1.0)
        return None

    def _teardown_profile(self, ssid: str) -> None:
        """Remove the broken profile so a retry creates a clean one."""
        try:
            nmcli_run(["connection", "delete", "id", ssid],
                      timeout=5, check=False, dry_run=self.dry_run)
        except WifiError:
            log.debug("teardown of profile %s failed (best-effort)", ssid)
