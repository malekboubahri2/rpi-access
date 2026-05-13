"""APManager SSID derivation tests."""
from __future__ import annotations

from rpi_access.wifi.ap import APManager


def test_derive_ssid_with_ethernet_ip(tmp_config):
    ap = APManager(tmp_config.network, dry_run=True)
    ssid = ap.derive_ssid(prefix="rpi-access", ethernet_ip="192.168.1.42")
    assert ssid == "rpi-192-168-1-42"
    assert len(ssid.encode("utf-8")) <= 32


def test_derive_ssid_without_ethernet_falls_back(tmp_config, monkeypatch):
    ap = APManager(tmp_config.network, dry_run=True)
    monkeypatch.setattr(ap, "_read_mac", lambda: "00:11:22:AA:BB:CC")
    ssid = ap.derive_ssid(prefix="rpi-access")
    assert ssid == "rpi-access-BBCC"


def test_derive_ssid_eth_ip_takes_precedence(tmp_config, monkeypatch):
    ap = APManager(tmp_config.network, dry_run=True)
    monkeypatch.setattr(ap, "_read_mac", lambda: "00:11:22:AA:BB:CC")
    ssid = ap.derive_ssid(prefix="rpi-access", ethernet_ip="10.0.0.1")
    assert ssid == "rpi-10-0-0-1"


def test_derive_ssid_random_when_mac_missing(tmp_config, monkeypatch):
    ap = APManager(tmp_config.network, dry_run=True)
    monkeypatch.setattr(ap, "_read_mac", lambda: None)
    ssid = ap.derive_ssid(prefix="rpi-access")
    assert ssid.startswith("rpi-access-")
    assert len(ssid) == len("rpi-access-") + 4
