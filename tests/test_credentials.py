"""Encrypted credential store tests."""
from __future__ import annotations

import pytest

from rpi_access.core.exceptions import CredentialError
from rpi_access.security.credentials import CredentialStore


def test_save_then_list(tmp_config):
    store = CredentialStore(tmp_config.security)
    store.save("Home", "supersecret")
    networks = store.list_known()
    assert [n.ssid for n in networks] == ["Home"]
    assert networks[0].has_password is True


def test_save_open_network(tmp_config):
    store = CredentialStore(tmp_config.security)
    store.save("OpenNet", None)
    network = store.list_known()[0]
    assert network.has_password is False
    assert store.get_password("OpenNet") is None


def test_get_password_roundtrip(tmp_config):
    store = CredentialStore(tmp_config.security)
    store.save("Home", "supersecret")
    assert store.get_password("Home") == "supersecret"


def test_save_overwrites(tmp_config):
    store = CredentialStore(tmp_config.security)
    store.save("Home", "first")
    store.save("Home", "second")
    assert store.get_password("Home") == "second"
    assert len(store.list_known()) == 1


def test_forget(tmp_config):
    store = CredentialStore(tmp_config.security)
    store.save("Home", "x" * 10)
    assert store.forget("Home") is True
    assert store.list_known() == []
    assert store.forget("Home") is False


def test_decryption_fails_with_wrong_key(tmp_config, tmp_path, monkeypatch):
    store = CredentialStore(tmp_config.security)
    store.save("Home", "secret123")

    # Overwrite master key with a different one.
    from cryptography.fernet import Fernet
    new_key = Fernet.generate_key()
    with open(tmp_config.security.key_file, "wb") as f:
        f.write(new_key)

    fresh = CredentialStore(tmp_config.security)
    with pytest.raises(CredentialError):
        fresh.list_known()


def test_file_permissions(tmp_config):
    """The on-disk artifacts should be 0600. Skip on non-POSIX where mode is fake."""
    import os
    import stat
    store = CredentialStore(tmp_config.security)
    store.save("Home", "secret123")
    for path in (tmp_config.security.key_file, tmp_config.security.credentials_file):
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if os.name == "posix":
            assert mode == 0o600, f"{path} is {oct(mode)}"
