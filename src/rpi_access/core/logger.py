"""Logging setup — rotating file + journald-friendly stderr.

We deliberately keep the formatter minimal so journald's own timestamping
doesn't double up. Passwords/PSKs must NEVER reach this logger; the
WifiClient is responsible for redacting them before any log call.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rpi_access.core.config import LoggingConfig

_LOG_NAME = "rpi-access"
_FORMAT = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def setup_logging(cfg: LoggingConfig) -> None:
    """Configure the root rpi-access logger. Idempotent."""
    global _configured
    if _configured:
        return

    level_name = os.environ.get("RPI_ACCESS_LOG_LEVEL", cfg.level).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger(_LOG_NAME)
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Always log to stderr (journald captures it).
    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # File handler — best-effort; skip silently if directory unwritable in dev.
    try:
        Path(cfg.file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            cfg.file, maxBytes=cfg.max_bytes, backupCount=cfg.backups, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("file logging disabled: %s", exc)

    # Quiet third-party noise.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the rpi_access namespace."""
    # Strip the leading package name if caller passes __name__.
    if name.startswith(_LOG_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOG_NAME}.{name}")
