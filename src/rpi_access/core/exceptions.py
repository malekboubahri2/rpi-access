"""Typed exceptions for rpi-access.

Keeping a small, deliberate exception hierarchy makes error handling at the
Flask / orchestrator boundary explicit — we map these to user-facing
messages and HTTP status codes rather than letting raw subprocess output
leak into responses.
"""
from __future__ import annotations


class RpiAccessError(Exception):
    """Base class for all rpi-access errors."""


class ConfigError(RpiAccessError):
    """Configuration file missing, malformed, or violates schema."""


class WifiError(RpiAccessError):
    """Generic WiFi / nmcli failure."""


class ScanError(WifiError):
    """`nmcli dev wifi list` failed or produced unparseable output."""


class ConnectError(WifiError):
    """`nmcli connection up` failed — wrong PSK, out of range, etc."""


class APError(RpiAccessError):
    """Failed to bring up or tear down the access point."""


class CredentialError(RpiAccessError):
    """Encrypted credential store failed (missing key, corrupt blob)."""


class ValidationError(RpiAccessError):
    """User-supplied data failed validation."""
