"""Typed configuration loader.

The config file is INI (stdlib `configparser`) so it is editable on a Pi
without pulling a YAML/TOML dependency just for config. We immediately
parse it into frozen dataclasses so the rest of the code never touches
strings.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from rpi_access.core.exceptions import ConfigError


# Defaults are duplicated from config/rpi-access.conf so that missing
# keys never crash the orchestrator on a partially-edited config.
_DEFAULTS: dict[str, dict[str, str]] = {
    "network": {
        "ap_ssid_prefix": "rpi-access",
        "ap_password": "",
        "ap_gateway": "192.168.4.1",
        "ap_subnet": "192.168.4.0/24",
        "ap_dhcp_start": "192.168.4.10",
        "ap_dhcp_end": "192.168.4.100",
        "wifi_interface": "wlan0",
        "scan_timeout_s": "15",
        "connect_timeout_s": "25",
        "connect_retries": "3",
        "ap_connection_name": "rpi-access-AP",
    },
    "portal": {
        "host": "0.0.0.0",
        "port": "80",
        "secret_key_file": "/etc/rpi-access/secret.key",
    },
    "security": {
        "credentials_file": "/etc/rpi-access/credentials.enc",
        "key_file": "/etc/rpi-access/master.key",
    },
    "logging": {
        "level": "INFO",
        "file": "/var/log/rpi-access/rpi-access.log",
        "max_bytes": "1048576",
        "backups": "5",
    },
}


@dataclass(frozen=True)
class NetworkConfig:
    ap_ssid_prefix: str
    ap_password: str
    ap_gateway: str
    ap_subnet: str
    ap_dhcp_start: str
    ap_dhcp_end: str
    wifi_interface: str
    scan_timeout_s: int
    connect_timeout_s: int
    connect_retries: int
    ap_connection_name: str


@dataclass(frozen=True)
class PortalConfig:
    host: str
    port: int
    secret_key_file: str


@dataclass(frozen=True)
class SecurityConfig:
    credentials_file: str
    key_file: str


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    file: str
    max_bytes: int
    backups: int


@dataclass(frozen=True)
class Config:
    network: NetworkConfig
    portal: PortalConfig
    security: SecurityConfig
    logging: LoggingConfig
    source_path: str = field(default="<defaults>")


def _coerce_int(section: str, key: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"[{section}].{key} must be an integer, got {raw!r}") from exc


def load_config(path: str | os.PathLike[str]) -> Config:
    """Load and validate a config file. Missing file is tolerated in dev mode."""
    parser = configparser.ConfigParser()
    parser.read_dict(_DEFAULTS)

    path = str(path)
    if os.path.exists(path):
        parser.read(path, encoding="utf-8")
        source = path
    else:
        if os.environ.get("RPI_ACCESS_DEV") != "1":
            raise ConfigError(f"config file not found: {path}")
        source = "<defaults>"

    n = parser["network"]
    network = NetworkConfig(
        ap_ssid_prefix=n.get("ap_ssid_prefix").strip(),
        ap_password=n.get("ap_password", ""),
        ap_gateway=n.get("ap_gateway").strip(),
        ap_subnet=n.get("ap_subnet").strip(),
        ap_dhcp_start=n.get("ap_dhcp_start").strip(),
        ap_dhcp_end=n.get("ap_dhcp_end").strip(),
        wifi_interface=n.get("wifi_interface").strip(),
        scan_timeout_s=_coerce_int("network", "scan_timeout_s", n.get("scan_timeout_s")),
        connect_timeout_s=_coerce_int("network", "connect_timeout_s", n.get("connect_timeout_s")),
        connect_retries=_coerce_int("network", "connect_retries", n.get("connect_retries")),
        ap_connection_name=n.get("ap_connection_name").strip(),
    )

    p = parser["portal"]
    portal = PortalConfig(
        host=p.get("host").strip(),
        port=_coerce_int("portal", "port", p.get("port")),
        secret_key_file=p.get("secret_key_file").strip(),
    )

    s = parser["security"]
    security = SecurityConfig(
        credentials_file=s.get("credentials_file").strip(),
        key_file=s.get("key_file").strip(),
    )

    lg = parser["logging"]
    logging_cfg = LoggingConfig(
        level=lg.get("level").strip().upper(),
        file=lg.get("file").strip(),
        max_bytes=_coerce_int("logging", "max_bytes", lg.get("max_bytes")),
        backups=_coerce_int("logging", "backups", lg.get("backups")),
    )

    # AP password is allowed to be empty (open AP); when set must be >=8 chars per WPA2.
    if network.ap_password and len(network.ap_password) < 8:
        raise ConfigError(
            "[network].ap_password must be empty or at least 8 characters (WPA2 minimum)."
        )

    cfg = Config(
        network=network,
        portal=portal,
        security=security,
        logging=logging_cfg,
        source_path=source,
    )
    return cfg


def ensure_runtime_dirs(cfg: Config) -> None:
    """Create the directories required at runtime if they don't exist."""
    log_dir = Path(cfg.logging.file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    cred_dir = Path(cfg.security.credentials_file).parent
    cred_dir.mkdir(parents=True, exist_ok=True)
