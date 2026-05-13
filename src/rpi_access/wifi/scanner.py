"""WiFi scanner — parse `nmcli -t -f` output into typed records.

We use the terse, field-selected output format to avoid pulling in a
heavier dependency just for parsing. The fields are escaped with `\\:`
inside values, which we have to unescape ourselves.

A note on AP mode and `ifname` scoping
--------------------------------------
On Raspberry Pi 3/4/5 the wifi radio runs in AP mode while we serve the
captive portal. In that state, asking `nmcli` for a scan **scoped to
the AP interface** (`nmcli device wifi list ifname wlan0`) returns
empty — wlan0 cannot enumerate other APs while it's committed to its
own. However, the *unscoped* form (`nmcli device wifi list`) returns
NetworkManager's global scan cache, which includes results gathered
before the AP came up plus whatever NM can passively pick up.

So the scanner deliberately does NOT pass `ifname` to the list command.
The `rescan` call still names the interface, because that's where the
radio actually lives — if NM refuses (busy in AP mode), we tolerate
the non-zero exit and just serve whatever's cached.

We also keep an in-process cache of the last successful parse so the
portal stays responsive even if the next list call hiccups.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from rpi_access.core.config import NetworkConfig
from rpi_access.core.exceptions import ScanError
from rpi_access.core.logger import get_logger
from rpi_access.wifi._nmcli import run as nmcli_run

log = get_logger(__name__)

# Field order requested from nmcli — keep stable, parser depends on it.
_FIELDS = "SSID,SIGNAL,SECURITY,FREQ,IN-USE,BSSID"


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int          # 0-100
    security: str         # "" for open, e.g. "WPA2" / "WPA1 WPA2"
    frequency: int        # MHz
    in_use: bool
    bssid: str

    @property
    def is_open(self) -> bool:
        return self.security in ("", "--")

    def to_dict(self) -> dict[str, object]:
        return {
            "ssid": self.ssid,
            "signal": self.signal,
            "security": self.security or "",
            "frequency": self.frequency,
            "in_use": self.in_use,
            "bssid": self.bssid,
            "is_open": self.is_open,
        }


class Scanner:
    """Wraps `nmcli dev wifi list` with parsing, deduplication, and a cache."""

    def __init__(self, cfg: NetworkConfig, *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self._cache: list[Network] = []
        self._cache_at: float = 0.0
        self._lock = threading.Lock()

    def rescan(self, timeout: float = 15.0) -> None:
        """Force a fresh scan (asks NM to re-scan, doesn't print)."""
        nmcli_run(
            ["device", "wifi", "rescan", "ifname", self.cfg.wifi_interface],
            timeout=timeout,
            check=False,  # NM returns non-zero if already scanning — fine
            dry_run=self.dry_run,
        )

    def scan(self, timeout: float = 15.0) -> list[Network]:
        """Trigger a rescan and return the latest list (also updates cache).

        IMPORTANT: the `list` query is intentionally *unscoped* (no
        `ifname`). When wlan0 is hosting the AP, `ifname wlan0` returns
        empty; the unscoped form returns NM's global scan cache, which
        is what we want.
        """
        # Tell NM to refresh. Scoped to the configured interface so we
        # don't accidentally trigger scans on unrelated devices. If
        # wlan0 is busy hosting the AP this returns non-zero — fine.
        self.rescan(timeout=timeout)

        result = nmcli_run(
            ["-t", "-f", _FIELDS, "device", "wifi", "list"],
            timeout=timeout,
            dry_run=self.dry_run,
        )
        if self.dry_run:
            return []
        networks = parse_scan_output(result.stdout)
        # Only overwrite the cache if we actually got results — an empty
        # response means "radio busy or cold cache", not "no networks".
        # Keep the previous (pre-AP) snapshot in that case.
        with self._lock:
            if networks or not self._cache:
                self._cache = networks
                self._cache_at = time.time()
        return networks

    def cached(self) -> tuple[list[Network], float]:
        """Return `(networks, unix_timestamp_of_last_scan)`.

        `unix_timestamp_of_last_scan` is 0.0 if nothing has been cached
        yet (i.e. the orchestrator hasn't run an initial scan).
        """
        with self._lock:
            return list(self._cache), self._cache_at


def _leading_int(raw: str) -> int | None:
    """Pull the leading integer off a possibly-unit-suffixed field.

    `"2457 MHz"` -> 2457, `"100%"` -> 100, `"  42 "` -> 42, `"--"` -> None.
    """
    if not raw:
        return None
    s = raw.strip()
    digits: list[str] = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        else:
            # Stop at the first non-digit so we don't accidentally
            # concatenate `2457` with anything after the space.
            break
    if not digits:
        return None
    return int("".join(digits))


def parse_scan_output(raw: str) -> list[Network]:
    """Parse the terse `nmcli -t` output.

    The format is `field1:field2:...` per line. Colons inside values are
    escaped as `\\:`. Empty SSID lines (hidden networks) are dropped.

    NetworkManager >= ~1.32 prints units on numeric fields even in
    terse mode (e.g. `FREQ=2457 MHz`, `SIGNAL=100%`). Older versions
    emit bare integers. We strip non-digits before converting so both
    work.
    """
    networks: dict[str, Network] = {}  # de-dupe by SSID, keep strongest signal

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = _split_terse(line)
        if len(fields) < 6:
            log.debug("skipping malformed scan line: %r", line)
            continue
        ssid_raw, signal_raw, security, freq_raw, in_use_raw, bssid = fields[:6]
        ssid = ssid_raw.strip()
        if not ssid:
            continue  # hidden network
        signal = _leading_int(signal_raw)
        frequency = _leading_int(freq_raw)
        if signal is None or frequency is None:
            log.debug("non-integer numeric in scan line: %r", line)
            continue

        net = Network(
            ssid=ssid,
            signal=max(0, min(signal, 100)),
            security=("" if security == "--" else security),
            frequency=frequency,
            in_use=(in_use_raw.strip() == "*"),
            bssid=bssid,
        )
        existing = networks.get(ssid)
        if existing is None or net.signal > existing.signal:
            networks[ssid] = net

    return sorted(networks.values(), key=lambda n: n.signal, reverse=True)


def _split_terse(line: str) -> list[str]:
    """Split a `nmcli -t` line on unescaped colons.

    `\\:` is an escaped colon and stays in the value. `\\\\` is a literal
    backslash. We process the string character-by-character because the
    field count is small and the input is trusted (locally-produced).
    """
    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            nxt = line[i + 1]
            if nxt in (":", "\\"):
                buf.append(nxt)
                i += 2
                continue
        if ch == ":":
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out
