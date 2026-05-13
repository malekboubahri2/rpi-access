"""Scanner cache behaviour (no real subprocess)."""
from __future__ import annotations

from rpi_access.wifi import scanner as scanner_mod
from rpi_access.wifi.scanner import Scanner


def _fake_nmcli(stdout: str):
    """Build a fake nmcli_run that returns canned stdout."""
    class _Result:
        rc = 0
        stderr = ""

        def __init__(self, out: str) -> None:
            self.stdout = out

    def _run(args, **_kwargs):
        # rescan call has no fields; list call has them. Differentiate.
        if "list" in args:
            return _Result(stdout)
        return _Result("")

    return _run


def test_scan_populates_cache(tmp_config, monkeypatch):
    monkeypatch.setattr(
        scanner_mod, "nmcli_run",
        _fake_nmcli("HomeWiFi:78:WPA2:2412:*:AA:BB:CC:DD:EE:FF\n"),
    )
    s = Scanner(tmp_config.network)
    cached, ts = s.cached()
    assert cached == []
    assert ts == 0.0
    nets = s.scan(timeout=1)
    assert [n.ssid for n in nets] == ["HomeWiFi"]
    cached, ts = s.cached()
    assert [n.ssid for n in cached] == ["HomeWiFi"]
    assert ts > 0


def test_empty_scan_does_not_wipe_existing_cache(tmp_config, monkeypatch):
    monkeypatch.setattr(
        scanner_mod, "nmcli_run",
        _fake_nmcli("HomeWiFi:78:WPA2:2412:*:AA:BB:CC:DD:EE:FF\n"),
    )
    s = Scanner(tmp_config.network)
    s.scan(timeout=1)
    cached_before, ts_before = s.cached()

    # Now switch to a fake that returns empty (simulates the AP-mode case
    # where nmcli briefly returns nothing).
    monkeypatch.setattr(scanner_mod, "nmcli_run", _fake_nmcli(""))
    nets = s.scan(timeout=1)
    assert nets == []  # the live call is empty
    cached_after, ts_after = s.cached()
    assert [n.ssid for n in cached_after] == [n.ssid for n in cached_before]
    assert ts_after == ts_before  # cache timestamp unchanged
