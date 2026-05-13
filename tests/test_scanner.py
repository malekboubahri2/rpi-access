"""Scanner output parsing tests — no subprocess calls."""
from __future__ import annotations

from rpi_access.wifi.scanner import parse_scan_output


def test_parse_basic():
    raw = (
        "HomeWiFi:78:WPA2:2412:*:AA:BB:CC:DD:EE:FF\n"
        "GuestNet:45:WPA1 WPA2:2437: :11:22:33:44:55:66\n"
        "Open5G:60:--:5180: :77:88:99:AA:BB:CC\n"
    )
    nets = parse_scan_output(raw)
    assert [n.ssid for n in nets] == ["HomeWiFi", "Open5G", "GuestNet"]
    home = next(n for n in nets if n.ssid == "HomeWiFi")
    assert home.signal == 78
    assert home.in_use is True
    assert home.security == "WPA2"
    open5g = next(n for n in nets if n.ssid == "Open5G")
    assert open5g.is_open
    assert open5g.security == ""


def test_parse_drops_hidden():
    raw = ":50:--:2412: :AA:BB:CC:DD:EE:FF\n"
    assert parse_scan_output(raw) == []


def test_parse_escaped_colon_in_ssid():
    # nmcli escapes literal colons in SSID as `\:`
    raw = r"Cafe\:Net:64:WPA2:2412: :AA:BB:CC:DD:EE:FF"
    nets = parse_scan_output(raw)
    assert len(nets) == 1
    assert nets[0].ssid == "Cafe:Net"


def test_parse_deduplicates_keeping_strongest():
    raw = (
        "SameNet:40:WPA2:2412: :AA:BB:CC:DD:EE:01\n"
        "SameNet:75:WPA2:2412: :AA:BB:CC:DD:EE:02\n"
        "SameNet:55:WPA2:2412: :AA:BB:CC:DD:EE:03\n"
    )
    nets = parse_scan_output(raw)
    assert len(nets) == 1
    assert nets[0].signal == 75


def test_parse_skips_malformed():
    raw = "garbage\n:::\nValid:30:--:2412: :AA:BB:CC:DD:EE:FF\n"
    nets = parse_scan_output(raw)
    assert [n.ssid for n in nets] == ["Valid"]


def test_parse_clamps_signal():
    raw = "Hot:150:--:2412: :AA:BB:CC:DD:EE:FF"
    assert parse_scan_output(raw)[0].signal == 100
