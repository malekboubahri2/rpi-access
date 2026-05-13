"""rpi-access - Raspberry Pi WiFi onboarding & captive portal.

Public surface kept minimal — callers should import from the submodules
(`rpi_access.core`, `rpi_access.wifi`, etc.) rather than the package
root so that we keep the import graph cheap on boot.
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "1.0.0"
