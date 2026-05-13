"""Access Point manager.

We deliberately do NOT spawn hostapd/dnsmasq directly — NetworkManager
on Bookworm ships its own AP support that handles both DHCP and DNS
through `nm-shared`. This keeps us off the "two DHCP servers fighting
for wlan0" rake.

If for some reason NM's shared mode is unavailable, the `config/hostapd.conf`
and `config/dnsmasq.conf` files in this repo are a known-good fallback —
see docs/troubleshooting.md for the manual recipe.
"""
from __future__ import annotations

import re
import uuid

from rpi_access.core.config import NetworkConfig
from rpi_access.core.exceptions import APError, WifiError
from rpi_access.core.logger import get_logger
from rpi_access.wifi._nmcli import run as nmcli_run

log = get_logger(__name__)

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


class APManager:
    """Bring an `nmcli` hotspot connection up/down deterministically."""

    def __init__(self, cfg: NetworkConfig, *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self._conn_name = cfg.ap_connection_name

    # ----- public API --------------------------------------------------------------

    def derive_ssid(self, prefix: str, ethernet_ip: str | None = None) -> str:
        """Pick an SSID for the AP.

        * If `ethernet_ip` is provided, encode it into the SSID so anyone in
          range can read the Pi's wired address off the WiFi list. The
          dot-separated address is dashed (`rpi-192-168-1-42`) to avoid
          quoting issues in shells and clients.
        * Otherwise, fall back to `<prefix>-<last 4 hex of wlan MAC>`.
        """
        if ethernet_ip:
            candidate = f"rpi-{ethernet_ip.replace('.', '-')}"
            # SSIDs are limited to 32 octets; a well-formed IPv4 fits
            # comfortably (max 19 chars) but guard against future surprises.
            if len(candidate.encode("utf-8")) <= 32:
                return candidate

        mac = self._read_mac()
        if mac:
            suffix = mac.replace(":", "")[-4:].upper()
        else:
            suffix = uuid.uuid4().hex[:4].upper()
        return f"{prefix}-{suffix}"

    def start(self, ssid: str) -> None:
        """Idempotently bring up an AP with the given SSID."""
        log.info("starting AP ssid=%s on %s", ssid, self.cfg.wifi_interface)

        # Tear down any previous instance so this is repeatable.
        self._delete_profile_if_exists()

        # Build the connection profile.
        try:
            self._add_profile(ssid)
            self._configure_profile()
            self._activate_profile()
        except WifiError as exc:
            raise APError(f"failed to start AP: {exc}") from exc

    def stop(self) -> None:
        """Bring the AP down and remove its profile."""
        log.info("stopping AP")
        try:
            nmcli_run(
                ["connection", "down", "id", self._conn_name],
                timeout=10, check=False, dry_run=self.dry_run,
            )
        except WifiError as exc:
            log.warning("AP down failed: %s", exc)
        self._delete_profile_if_exists()

    # ----- internals --------------------------------------------------------------

    def _add_profile(self, ssid: str) -> None:
        args = [
            "connection", "add",
            "type", "wifi",
            "ifname", self.cfg.wifi_interface,
            "con-name", self._conn_name,
            "autoconnect", "no",
            "ssid", ssid,
        ]
        nmcli_run(args, timeout=10, dry_run=self.dry_run)

    def _configure_profile(self) -> None:
        # 802-11-wireless mode=ap, channel=6 (2.4 GHz - most compatible).
        nmcli_run(
            [
                "connection", "modify", self._conn_name,
                "802-11-wireless.mode", "ap",
                "802-11-wireless.band", "bg",
                "802-11-wireless.channel", "6",
                "ipv4.method", "shared",
                "ipv4.addresses", f"{self.cfg.ap_gateway}/24",
                "ipv6.method", "disabled",
            ],
            timeout=10, dry_run=self.dry_run,
        )

        if self.cfg.ap_password:
            # WPA2 — wpa-psk key management.
            args = [
                "connection", "modify", self._conn_name,
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", self.cfg.ap_password,
            ]
            # 0=connection,1=modify,2=name,3=wifi-sec.key-mgmt,4=wpa-psk,
            # 5=wifi-sec.psk,6=<psk>
            nmcli_run(args, timeout=10, redact_index=6, dry_run=self.dry_run)
        else:
            # Explicitly clear key-mgmt for open networks.
            nmcli_run(
                ["connection", "modify", self._conn_name,
                 "wifi-sec.key-mgmt", ""],
                timeout=10, check=False, dry_run=self.dry_run,
            )

    def _activate_profile(self) -> None:
        nmcli_run(
            ["connection", "up", "id", self._conn_name],
            timeout=15, dry_run=self.dry_run,
        )

    def _delete_profile_if_exists(self) -> None:
        try:
            res = nmcli_run(
                ["-t", "-f", "NAME", "connection", "show"],
                timeout=5, dry_run=self.dry_run, check=False,
            )
        except WifiError:
            return
        if self.dry_run:
            return
        names = {line.strip() for line in res.stdout.splitlines() if line.strip()}
        if self._conn_name in names:
            nmcli_run(
                ["connection", "delete", "id", self._conn_name],
                timeout=10, check=False, dry_run=self.dry_run,
            )

    def _read_mac(self) -> str | None:
        try:
            with open(f"/sys/class/net/{self.cfg.wifi_interface}/address", encoding="ascii") as f:
                mac = f.read().strip()
            if _MAC_RE.fullmatch(mac):
                return mac
        except OSError:
            pass
        return None
