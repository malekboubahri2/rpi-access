"""WiFi scanner — parse `nmcli -t -f` output into typed records.

We use the terse, field-selected output format to avoid pulling in a
heavier dependency just for parsing. The fields are escaped with `\\:`
inside values, which we have to unescape ourselves.
"""
from __future__ import annotations

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
    """Wraps `nmcli dev wifi list` with parsing & deduplication."""

    def __init__(self, cfg: NetworkConfig, *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run

    def rescan(self, timeout: float = 15.0) -> None:
        """Force a fresh scan (asks NM to re-scan, doesn't print)."""
        nmcli_run(
            ["device", "wifi", "rescan", "ifname", self.cfg.wifi_interface],
            timeout=timeout,
            check=False,  # NM returns non-zero if already scanning — fine
            dry_run=self.dry_run,
        )

    def scan(self, timeout: float = 15.0) -> list[Network]:
        """Return a deduplicated list of nearby networks, strongest first."""
        self.rescan(timeout=timeout)
        result = nmcli_run(
            [
                "-t",
                "-f",
                _FIELDS,
                "device",
                "wifi",
                "list",
                "ifname",
                self.cfg.wifi_interface,
            ],
            timeout=timeout,
            dry_run=self.dry_run,
        )
        if self.dry_run:
            return []
        return parse_scan_output(result.stdout)


def parse_scan_output(raw: str) -> list[Network]:
    """Parse the terse `nmcli -t` output.

    The format is `field1:field2:...` per line. Colons inside values are
    escaped as `\\:`. Empty SSID lines (hidden networks) are dropped.
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
        try:
            signal = int(signal_raw)
            frequency = int(freq_raw)
        except ValueError:
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
