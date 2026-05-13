"""Input validation for SSIDs and pre-shared keys.

These rules come from IEEE 802.11 (SSID 1-32 octets, no NUL) and WPA2
(8-63 ASCII chars or 64 hex). We reject anything outside these bounds
*before* it reaches nmcli — partly to give better error messages, partly
because some characters (notably NUL) break the nmcli CLI.
"""
from __future__ import annotations

import string

from rpi_access.core.exceptions import ValidationError

# Printable ASCII is the safe subset. Real-world routers occasionally use
# UTF-8 SSIDs, but we follow nmcli's recommendation and only accept the
# bytes we know round-trip cleanly through the shell.
_PRINTABLE = set(string.printable) - {"\x0b", "\x0c"}  # drop VT/FF


def validate_ssid(ssid: str) -> str:
    """Return a cleaned SSID or raise ValidationError."""
    if not isinstance(ssid, str):
        raise ValidationError("SSID must be a string")
    cleaned = ssid.strip("\x00")  # NUL is illegal in 802.11 SSIDs
    if cleaned != ssid:
        raise ValidationError("SSID contains illegal NUL byte")
    if not cleaned:
        raise ValidationError("SSID is empty")
    encoded = cleaned.encode("utf-8")
    if len(encoded) > 32:
        raise ValidationError("SSID exceeds 32 octets")
    if any(ch in ("\r", "\n") for ch in cleaned):
        raise ValidationError("SSID contains line breaks")
    # We allow Unicode, but reject control chars (< 0x20) explicitly.
    if any(ord(ch) < 0x20 and ch != "\t" for ch in cleaned):
        raise ValidationError("SSID contains control characters")
    return cleaned


def validate_psk(psk: str | None, *, allow_empty: bool = True) -> str | None:
    """Return a validated PSK or None for an open network.

    Empty string and None both mean 'open'. A non-empty value must be
    either 8-63 printable ASCII chars (passphrase) or exactly 64 hex
    digits (raw key).
    """
    if psk is None or psk == "":
        if not allow_empty:
            raise ValidationError("Password is required for this network")
        return None
    if not isinstance(psk, str):
        raise ValidationError("Password must be a string")
    if len(psk) == 64 and all(ch in string.hexdigits for ch in psk):
        return psk.lower()
    if 8 <= len(psk) <= 63 and all(ch in _PRINTABLE for ch in psk):
        return psk
    raise ValidationError(
        "Password must be 8-63 ASCII chars or 64 hex digits."
    )
