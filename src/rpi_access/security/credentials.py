"""Encrypted credential store.

Layout on disk:

    /etc/rpi-access/master.key       # Fernet key, root:root 0600
    /etc/rpi-access/credentials.enc  # Fernet ciphertext, root:root 0600

The plaintext payload is a small JSON document:

    {"networks": [{"ssid": "Home", "psk": "...", "saved_at": 17...}]}

We use Fernet from the `cryptography` package because it's the most
boring symmetric-encryption choice — authenticated, versioned, and ships
with a 5-line API.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from rpi_access.core.config import SecurityConfig
from rpi_access.core.exceptions import CredentialError
from rpi_access.core.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SavedNetwork:
    ssid: str
    saved_at: float
    has_password: bool


@dataclass
class _Document:
    networks: list[dict[str, object]] = field(default_factory=list)

    def to_json(self) -> bytes:
        return json.dumps({"networks": self.networks}, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json(cls, blob: bytes) -> "_Document":
        try:
            data = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialError(f"credentials blob is corrupt: {exc}") from exc
        nets = data.get("networks", [])
        if not isinstance(nets, list):
            raise CredentialError("credentials blob has unexpected shape")
        return cls(networks=nets)


class CredentialStore:
    """File-backed, Fernet-encrypted credential store."""

    def __init__(self, cfg: SecurityConfig) -> None:
        self.cfg = cfg
        self._fernet: Fernet | None = None

    # ----- public API --------------------------------------------------------------

    def list_known(self) -> list[SavedNetwork]:
        doc = self._read_doc()
        out = []
        for entry in doc.networks:
            ssid = entry.get("ssid")
            if not isinstance(ssid, str):
                continue
            out.append(SavedNetwork(
                ssid=ssid,
                saved_at=float(entry.get("saved_at", 0.0)),
                has_password=bool(entry.get("psk")),
            ))
        return out

    def get_password(self, ssid: str) -> str | None:
        doc = self._read_doc()
        for entry in doc.networks:
            if entry.get("ssid") == ssid:
                psk = entry.get("psk")
                return psk if isinstance(psk, str) and psk else None
        return None

    def save(self, ssid: str, psk: str | None) -> None:
        """Insert/update credentials for `ssid`. Never logs the PSK itself."""
        log.info("saving credentials for ssid=%s (password=%s)",
                 ssid, "set" if psk else "open")
        doc = self._read_doc()
        doc.networks = [e for e in doc.networks if e.get("ssid") != ssid]
        doc.networks.append({
            "ssid": ssid,
            "psk": psk or "",
            "saved_at": time.time(),
        })
        self._write_doc(doc)

    def forget(self, ssid: str) -> bool:
        """Remove a saved network. Returns True if anything was deleted."""
        doc = self._read_doc()
        before = len(doc.networks)
        doc.networks = [e for e in doc.networks if e.get("ssid") != ssid]
        if len(doc.networks) == before:
            return False
        self._write_doc(doc)
        log.info("forgot credentials for ssid=%s", ssid)
        return True

    # ----- internals --------------------------------------------------------------

    def _fernet_key(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet

        env_key = os.environ.get("RPI_ACCESS_MASTER_KEY")
        if env_key:
            try:
                self._fernet = Fernet(env_key.encode("ascii"))
                return self._fernet
            except (ValueError, TypeError) as exc:
                raise CredentialError(f"RPI_ACCESS_MASTER_KEY invalid: {exc}") from exc

        path = Path(self.cfg.key_file)
        if not path.exists():
            # In dev mode, create the key transparently. Production should
            # have setup.sh generate it during install.
            if os.environ.get("RPI_ACCESS_DEV") == "1":
                self._create_key(path)
            else:
                raise CredentialError(
                    f"master key file missing: {path} — run setup.sh"
                )
        try:
            with path.open("rb") as fh:
                key = fh.read().strip()
            self._fernet = Fernet(key)
        except (OSError, ValueError) as exc:
            raise CredentialError(f"unable to load master key: {exc}") from exc
        return self._fernet

    def _create_key(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        # Write 0600. os.open avoids the umask race that open() has.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        log.info("generated new master key at %s", path)

    def _read_doc(self) -> _Document:
        path = Path(self.cfg.credentials_file)
        if not path.exists():
            return _Document()
        try:
            with path.open("rb") as fh:
                blob = fh.read()
        except OSError as exc:
            raise CredentialError(f"cannot read credentials: {exc}") from exc
        if not blob:
            return _Document()
        f = self._fernet_key()
        try:
            plaintext = f.decrypt(blob)
        except InvalidToken as exc:
            raise CredentialError("credentials decryption failed (wrong key?)") from exc
        return _Document.from_json(plaintext)

    def _write_doc(self, doc: _Document) -> None:
        path = Path(self.cfg.credentials_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        f = self._fernet_key()
        cipher = f.encrypt(doc.to_json())
        # Atomic write: temp file + os.replace.
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, cipher)
        finally:
            os.close(fd)
        os.replace(tmp, path)
