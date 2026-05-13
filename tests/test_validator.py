"""SSID + PSK validator tests."""
from __future__ import annotations

import pytest

from rpi_access.core.exceptions import ValidationError
from rpi_access.security.validator import validate_psk, validate_ssid


class TestValidateSSID:
    def test_accepts_plain_ascii(self):
        assert validate_ssid("Home WiFi") == "Home WiFi"

    def test_accepts_unicode(self):
        assert validate_ssid("Café 5G") == "Café 5G"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            validate_ssid("")

    def test_rejects_non_string(self):
        with pytest.raises(ValidationError):
            validate_ssid(None)  # type: ignore[arg-type]

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            validate_ssid("a" * 33)

    def test_rejects_nul_byte(self):
        with pytest.raises(ValidationError):
            validate_ssid("Home\x00")

    def test_rejects_newline(self):
        with pytest.raises(ValidationError):
            validate_ssid("Home\n")

    def test_rejects_control_char(self):
        with pytest.raises(ValidationError):
            validate_ssid("Home\x01")


class TestValidatePSK:
    def test_none_means_open(self):
        assert validate_psk(None) is None

    def test_empty_string_means_open(self):
        assert validate_psk("") is None

    def test_disallow_empty_when_required(self):
        with pytest.raises(ValidationError):
            validate_psk("", allow_empty=False)

    def test_accepts_8_char_passphrase(self):
        assert validate_psk("password") == "password"

    def test_accepts_63_char_passphrase(self):
        p = "a" * 63
        assert validate_psk(p) == p

    def test_rejects_short_passphrase(self):
        with pytest.raises(ValidationError):
            validate_psk("short")

    def test_accepts_64_hex_raw_key(self):
        raw = "a" * 64
        assert validate_psk(raw) == raw

    def test_normalises_hex_to_lower(self):
        raw = "A" * 64
        assert validate_psk(raw) == "a" * 64

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValidationError):
            validate_psk("pass\x00word")
