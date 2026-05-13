"""Boot-time state machine.

The orchestrator walks through these states. They're a finite, ordered
set; transitions are restricted so we can't accidentally jump from
`PORTAL` straight to `CLIENT` without going through `CONNECTING`.

The state machine is also surfaced to the UI (`GET /api/status`) so the
user sees real progress instead of a spinner.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    BOOT = "boot"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CLIENT = "client"          # connected to upstream WiFi as a client
    AP_STARTING = "ap_starting"
    PORTAL = "portal"           # AP up, captive portal serving
    BEACON = "beacon"           # ethernet up, AP advertises its IP via SSID
    DIRECT = "direct"           # user opted to stay on AP indefinitely
    ERROR = "error"
    STOPPED = "stopped"


# Allowed transitions. Anything not in this map raises ValueError in
# `Transition.assert_valid`. Keep it strict — silent illegal transitions
# would make the boot flow impossible to debug from logs.
_ALLOWED: dict[State, frozenset[State]] = {
    State.BOOT: frozenset({State.SCANNING, State.AP_STARTING, State.ERROR, State.STOPPED}),
    State.SCANNING: frozenset({State.CONNECTING, State.AP_STARTING, State.ERROR, State.STOPPED}),
    State.CONNECTING: frozenset({State.CLIENT, State.AP_STARTING, State.SCANNING, State.ERROR, State.STOPPED}),
    State.CLIENT: frozenset({State.SCANNING, State.AP_STARTING, State.BEACON, State.ERROR, State.STOPPED}),
    State.AP_STARTING: frozenset({State.PORTAL, State.BEACON, State.ERROR, State.STOPPED}),
    State.PORTAL: frozenset({State.CONNECTING, State.DIRECT, State.BEACON, State.AP_STARTING, State.ERROR, State.STOPPED}),
    State.BEACON: frozenset({State.AP_STARTING, State.SCANNING, State.CONNECTING, State.ERROR, State.STOPPED}),
    State.DIRECT: frozenset({State.CONNECTING, State.STOPPED}),
    State.ERROR: frozenset({State.SCANNING, State.AP_STARTING, State.STOPPED}),
    State.STOPPED: frozenset(),
}


@dataclass(frozen=True)
class Transition:
    src: State
    dst: State

    def assert_valid(self) -> None:
        if self.dst not in _ALLOWED.get(self.src, frozenset()):
            raise ValueError(f"illegal transition: {self.src.value} -> {self.dst.value}")
