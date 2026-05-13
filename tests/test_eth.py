"""Ethernet helper tests (no real `ip` subprocess)."""
from __future__ import annotations

import subprocess

import pytest

from rpi_access.wifi import eth


class _FakeProc:
    def __init__(self, stdout: str, rc: int = 0) -> None:
        self.stdout = stdout
        self.returncode = rc


@pytest.fixture
def fake_ip(monkeypatch):
    """Patch `ip addr show` to return canned output."""
    state = {"output": "", "rc": 0}

    def _run(*args, **kwargs):  # noqa: ANN001
        return _FakeProc(state["output"], state["rc"])

    monkeypatch.setattr(eth.subprocess, "run", _run)
    monkeypatch.setattr(eth.shutil, "which", lambda _: "/usr/bin/ip")
    return state


def test_no_iface_returns_none(fake_ip):
    assert eth.get_ethernet_ip("") is None


def test_no_ip_binary_returns_none(monkeypatch):
    monkeypatch.setattr(eth.shutil, "which", lambda _: None)
    assert eth.get_ethernet_ip("eth0") is None


def test_simple_ipv4(fake_ip):
    fake_ip["output"] = (
        "3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n"
        "    inet 192.168.1.42/24 brd 192.168.1.255 scope global dynamic eth0\n"
    )
    assert eth.get_ethernet_ip("eth0") == "192.168.1.42"


def test_skips_link_local(fake_ip):
    fake_ip["output"] = "    inet 169.254.10.1/16 scope link eth0\n"
    assert eth.get_ethernet_ip("eth0") is None


def test_prefers_first_global_over_link_local(fake_ip):
    fake_ip["output"] = (
        "    inet 169.254.10.1/16 scope link eth0\n"
        "    inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0\n"
    )
    assert eth.get_ethernet_ip("eth0") == "10.0.0.5"


def test_nonzero_rc(fake_ip):
    fake_ip["rc"] = 1
    fake_ip["output"] = "Device \"eth0\" does not exist."
    assert eth.get_ethernet_ip("eth0") is None


def test_timeout_returns_none(monkeypatch):
    def _raise(*args, **kwargs):  # noqa: ANN001
        raise subprocess.TimeoutExpired(cmd=["ip"], timeout=4)

    monkeypatch.setattr(eth.shutil, "which", lambda _: "/usr/bin/ip")
    monkeypatch.setattr(eth.subprocess, "run", _raise)
    assert eth.get_ethernet_ip("eth0") is None
