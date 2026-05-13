"""State machine transition tests."""
from __future__ import annotations

import pytest

from rpi_access.core.state import State, Transition


@pytest.mark.parametrize(
    "src,dst",
    [
        (State.BOOT, State.SCANNING),
        (State.SCANNING, State.CONNECTING),
        (State.CONNECTING, State.CLIENT),
        (State.CONNECTING, State.AP_STARTING),
        (State.AP_STARTING, State.PORTAL),
        (State.AP_STARTING, State.BEACON),
        (State.PORTAL, State.CONNECTING),
        (State.PORTAL, State.DIRECT),
        (State.PORTAL, State.BEACON),
        (State.BEACON, State.SCANNING),
        (State.BEACON, State.AP_STARTING),
        (State.CLIENT, State.SCANNING),
        (State.CLIENT, State.BEACON),
    ],
)
def test_valid_transition(src, dst):
    Transition(src=src, dst=dst).assert_valid()  # does not raise


@pytest.mark.parametrize(
    "src,dst",
    [
        (State.BOOT, State.CLIENT),         # must scan first
        (State.PORTAL, State.CLIENT),       # must go through CONNECTING
        (State.STOPPED, State.SCANNING),    # terminal
        (State.DIRECT, State.PORTAL),       # cannot fall back into portal
        (State.BEACON, State.PORTAL),       # leave beacon via scan/connect
    ],
)
def test_invalid_transition(src, dst):
    with pytest.raises(ValueError):
        Transition(src=src, dst=dst).assert_valid()
