"""Shared pytest fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the src layout is importable without an install.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("RPI_ACCESS_DEV", "1")

import pytest

from rpi_access.core.config import (
    Config,
    LoggingConfig,
    NetworkConfig,
    PortalConfig,
    SecurityConfig,
)


@pytest.fixture
def tmp_config(tmp_path) -> Config:
    return Config(
        network=NetworkConfig(
            ap_ssid_prefix="rpi-access",
            ap_password="",
            ap_gateway="192.168.4.1",
            ap_subnet="192.168.4.0/24",
            ap_dhcp_start="192.168.4.10",
            ap_dhcp_end="192.168.4.100",
            wifi_interface="wlan0",
            scan_timeout_s=5,
            connect_timeout_s=5,
            connect_retries=1,
            ap_connection_name="rpi-access-AP",
        ),
        portal=PortalConfig(
            host="127.0.0.1",
            port=8080,
            secret_key_file=str(tmp_path / "secret.key"),
        ),
        security=SecurityConfig(
            credentials_file=str(tmp_path / "creds.enc"),
            key_file=str(tmp_path / "master.key"),
        ),
        logging=LoggingConfig(
            level="DEBUG",
            file=str(tmp_path / "edge.log"),
            max_bytes=1024,
            backups=1,
        ),
        source_path="<test>",
    )
