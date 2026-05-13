"""Thin, audited wrapper around the `nmcli` binary.

Centralising the subprocess call means:

* one place to honour `dry_run`,
* one place to redact passwords from logs,
* one place to handle timeouts and exit codes consistently.

Callers MUST pass arguments as a list (never a shell string) and MUST
pass `redact_index=` for any argv slot that contains a PSK so it never
hits the log.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from rpi_access.core.exceptions import WifiError
from rpi_access.core.logger import get_logger

log = get_logger(__name__)

NMCLI_BIN = "nmcli"
_REDACTED = "<redacted>"


@dataclass(frozen=True)
class NmcliResult:
    args: list[str]
    rc: int
    stdout: str
    stderr: str


def nmcli_available() -> bool:
    return shutil.which(NMCLI_BIN) is not None


def run(
    args: list[str],
    *,
    timeout: float = 30.0,
    redact_index: int | None = None,
    check: bool = True,
    dry_run: bool = False,
) -> NmcliResult:
    """Execute `nmcli <args>` and return its result.

    Parameters
    ----------
    args:
        Argument vector — `nmcli` is prepended automatically.
    timeout:
        Hard wall-clock limit. nmcli itself can sometimes hang on bad
        kernel state, so we always cap it.
    redact_index:
        Index in `args` whose value should be replaced with `<redacted>`
        before logging. Used for the PSK in `... password <psk>`.
    check:
        If True, raise WifiError on a non-zero exit.
    dry_run:
        If True, log the command and return a stub success.
    """
    safe = list(args)
    if redact_index is not None and 0 <= redact_index < len(safe):
        safe[redact_index] = _REDACTED

    # INFO so operators can grep `journalctl -u rpi-access` for what we
    # asked nmcli to do; PSKs are already redacted above.
    log.info("nmcli %s", " ".join(safe))

    if dry_run:
        return NmcliResult(args=safe, rc=0, stdout="", stderr="dry-run")

    if not nmcli_available():
        raise WifiError("nmcli not found on PATH — is NetworkManager installed?")

    try:
        proc = subprocess.run(  # noqa: S603 - args are a controlled list
            [NMCLI_BIN, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WifiError(f"nmcli timed out after {timeout}s: {' '.join(safe)}") from exc
    except FileNotFoundError as exc:
        raise WifiError("nmcli binary missing") from exc

    result = NmcliResult(args=safe, rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and proc.returncode != 0:
        # nmcli error messages are usually one-liners and safe to surface.
        raise WifiError(
            f"nmcli failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return result
