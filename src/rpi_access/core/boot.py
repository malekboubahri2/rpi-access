"""Boot orchestrator.

This is the long-running process invoked by `rpi-access.service`. It
walks the state machine in `core.state` and is the only thing that mutates
network state. The Flask portal pokes it via thread-safe transition
requests rather than calling nmcli directly.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from rpi_access.core.config import Config
from rpi_access.core.exceptions import ConnectError, ScanError
from rpi_access.core.logger import get_logger
from rpi_access.core.state import State, Transition
from rpi_access.security.credentials import CredentialStore
from rpi_access.wifi.ap import APManager
from rpi_access.wifi.client import WifiClient
from rpi_access.wifi.eth import get_ethernet_ip
from rpi_access.wifi.scanner import Scanner

# `app` is imported lazily inside `_start_portal` so importing
# `BootOrchestrator` doesn't pay the Flask import cost on every script.

log = get_logger(__name__)


@dataclass
class OrchestratorStatus:
    state: State = State.BOOT
    detail: str = ""
    ssid: str | None = None
    ip_address: str | None = None
    error: str | None = None
    ap_ssid: str | None = None
    ethernet_ip: str | None = None
    history: list[str] = field(default_factory=list)


class BootOrchestrator:
    """State-machine driver.

    The portal interacts with the orchestrator through three methods:

    * `request_connect(ssid, psk)` — try to join a new network.
    * `request_direct_mode()`     — keep AP up indefinitely.
    * `request_retry()`           — re-enter SCANNING.

    All requests are queued and processed by the orchestrator thread,
    never executed inline from the Flask request thread — this keeps
    nmcli calls serialised.
    """

    def __init__(self, cfg: Config, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.status = OrchestratorStatus()

        self.scanner = Scanner(cfg.network, dry_run=dry_run)
        self.client = WifiClient(cfg.network, dry_run=dry_run)
        self.ap = APManager(cfg.network, dry_run=dry_run)
        self.credentials = CredentialStore(cfg.security)

        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._pending: Callable[[], None] | None = None
        self._portal_thread = None  # set when AP comes up

    # ----- public control surface --------------------------------------------------

    def request_stop(self) -> None:
        log.info("stop requested")
        self._stop.set()

    def request_connect(self, ssid: str, psk: str | None) -> None:
        """Queue a connect attempt. Returns immediately."""
        with self._lock:
            log.info("connect requested ssid=%s", ssid)
            self._pending = lambda s=ssid, p=psk: self._handle_connect_request(s, p)

    def request_direct_mode(self) -> None:
        with self._lock:
            log.info("direct mode requested")
            self._pending = self._handle_direct_request

    def request_retry(self) -> None:
        with self._lock:
            log.info("retry requested")
            self._pending = self._handle_retry_request

    def snapshot(self) -> OrchestratorStatus:
        """Return a copy of the current status (thread-safe)."""
        with self._lock:
            return OrchestratorStatus(
                state=self.status.state,
                detail=self.status.detail,
                ssid=self.status.ssid,
                ip_address=self.status.ip_address,
                error=self.status.error,
                ap_ssid=self.status.ap_ssid,
                ethernet_ip=self.status.ethernet_ip,
                history=list(self.status.history),
            )

    # ----- main loop ---------------------------------------------------------------

    def run(self) -> int:
        """Walk the state machine until stopped. Returns a process exit code."""
        log.info("orchestrator starting (config=%s, dry_run=%s)",
                 self.cfg.source_path, self.dry_run)
        try:
            # Ethernet-first: if a wired link is already serving an IP at
            # boot, skip WiFi onboarding entirely and broadcast that
            # address through the AP SSID so the operator can SSH in over
            # the wired LAN without an mDNS lookup.
            eth_ip = self._refresh_ethernet_ip()
            if eth_ip:
                log.info("ethernet active (%s) — entering BEACON mode", eth_ip)
                self._transition(State.SCANNING, "ethernet detected, skipping scan")
                self._enter_beacon_mode(eth_ip)
            else:
                self._transition(State.SCANNING, "initial scan")
                self._try_known_networks()
            self._serve_until_stop()
        except Exception as exc:  # noqa: BLE001 - top-level handler
            log.exception("orchestrator crashed: %s", exc)
            self._transition(State.ERROR, f"unhandled: {exc}")
            return 1
        finally:
            self._transition(State.STOPPED, "shutdown")
        return 0

    def _serve_until_stop(self) -> None:
        """Idle loop — handle queued portal requests, otherwise sleep.

        We don't busy-loop; portal requests set `_pending` and we just check
        it every second. If the device drops off WiFi while in CLIENT, we
        attempt a quiet reconnect. While the AP is up (PORTAL, BEACON,
        DIRECT) we also poll the ethernet IP and refresh the SSID when it
        changes — that keeps the broadcast address accurate after a DHCP
        renewal or a cable swap.
        """
        last_health_check = 0.0
        last_eth_check = 0.0
        eth_poll = max(2, self.cfg.network.ethernet_poll_s)

        while not self._stop.is_set():
            req: Callable[[], None] | None
            with self._lock:
                req = self._pending
                self._pending = None
            if req is not None:
                try:
                    req()
                except Exception as exc:  # noqa: BLE001
                    log.exception("queued request failed: %s", exc)
                    self.status.error = str(exc)
                continue

            now = time.monotonic()

            # Periodic health check (every 30s) when in CLIENT state.
            if self.status.state == State.CLIENT and now - last_health_check > 30:
                last_health_check = now
                self._check_client_health()

            # Ethernet poll. Frequent enough to feel live; cheap (single
            # `ip addr show`).
            if now - last_eth_check > eth_poll:
                last_eth_check = now
                self._reconcile_ethernet()

            self._stop.wait(timeout=1.0)

    # ----- queued request handlers -------------------------------------------------

    def _handle_connect_request(self, ssid: str, psk: str | None) -> None:
        self._transition(State.CONNECTING, f"user-requested connect to {ssid}")
        try:
            ip = self.client.connect(ssid, psk, timeout=self.cfg.network.connect_timeout_s)
        except ConnectError as exc:
            log.warning("connect to %s failed: %s", ssid, exc)
            self.status.error = "Connection failed. Check the password and try again."
            # Stay in PORTAL state so the user can retry.
            self._transition(State.AP_STARTING, "connect failed, reviving AP")
            self.ap.start(self._ap_ssid())
            self._transition(State.PORTAL, "AP back up after failed connect")
            return

        # Success — persist creds, tear down AP, go CLIENT.
        try:
            self.credentials.save(ssid, psk)
        except Exception as exc:  # noqa: BLE001
            log.warning("credential save failed (non-fatal): %s", exc)

        self.ap.stop()
        self.status.ssid = ssid
        self.status.ip_address = ip
        self.status.error = None
        self._transition(State.CLIENT, f"connected, ip={ip}")

    def _handle_direct_request(self) -> None:
        if self.status.state not in (State.PORTAL, State.AP_STARTING):
            log.warning("direct-mode requested from unexpected state %s", self.status.state)
            return
        self._transition(State.DIRECT, "user opted for direct mode — AP stays up")

    def _handle_retry_request(self) -> None:
        self._transition(State.SCANNING, "user-requested retry")
        self._try_known_networks()

    # ----- helpers -----------------------------------------------------------------

    def _try_known_networks(self) -> None:
        try:
            networks = self.scanner.scan(timeout=self.cfg.network.scan_timeout_s)
        except ScanError as exc:
            log.warning("scan failed: %s", exc)
            networks = []

        saved = self.credentials.list_known()
        targets = [n for n in networks if n.ssid in {c.ssid for c in saved}]
        if not targets:
            log.info("no known networks visible (%d scanned, %d saved)", len(networks), len(saved))
            self._enter_ap_mode()
            return

        for net in targets:
            psk = self.credentials.get_password(net.ssid)
            self._transition(State.CONNECTING, f"trying known network {net.ssid}")
            try:
                ip = self.client.connect(net.ssid, psk,
                                         timeout=self.cfg.network.connect_timeout_s)
                self.status.ssid = net.ssid
                self.status.ip_address = ip
                self._transition(State.CLIENT, f"connected to {net.ssid}")
                return
            except ConnectError as exc:
                log.warning("known network %s failed: %s", net.ssid, exc)
                continue

        log.info("all known networks failed — falling back to AP")
        self._enter_ap_mode()

    def _enter_ap_mode(self) -> None:
        ssid = self._ap_ssid()
        self.status.ap_ssid = ssid
        self._transition(State.AP_STARTING, f"bringing up AP {ssid}")
        self.ap.start(ssid)
        self._start_portal()
        self._transition(State.PORTAL, "captive portal serving")

    def _enter_beacon_mode(self, ethernet_ip: str) -> None:
        """Bring the AP up with an SSID that announces the eth IP."""
        ssid = self._ap_ssid(ethernet_ip=ethernet_ip)
        self.status.ap_ssid = ssid
        self.status.ethernet_ip = ethernet_ip
        self._transition(State.AP_STARTING, f"beacon AP {ssid}")
        self.ap.start(ssid)
        # Portal still useful here — operator can also onboard to WiFi
        # from a phone if they want, even though SSH-over-eth is the
        # primary path.
        self._start_portal()
        self._transition(State.BEACON, f"beacon broadcasting ethernet IP {ethernet_ip}")

    def _start_portal(self) -> None:
        """Spin up the Flask portal in a daemon thread. Idempotent."""
        if self._portal_thread is not None:
            return
        # Lazy import — keeps `BootOrchestrator` cheap when only the
        # state machine is needed (e.g. in unit tests).
        from rpi_access.app import create_app, run_in_thread

        app = create_app(self.cfg, orchestrator=self)
        self._portal_thread = run_in_thread(
            app, host=self.cfg.portal.host, port=self.cfg.portal.port
        )
        log.info("portal thread started (%s:%s)",
                 self.cfg.portal.host, self.cfg.portal.port)

    def _ap_ssid(self, ethernet_ip: str | None = None) -> str:
        """Compose the AP SSID; encodes the ethernet IP when supplied."""
        return self.ap.derive_ssid(
            prefix=self.cfg.network.ap_ssid_prefix,
            ethernet_ip=ethernet_ip,
        )

    def _refresh_ethernet_ip(self) -> str | None:
        """Re-read the ethernet IP and update status. Returns the IP or None."""
        iface = self.cfg.network.ethernet_interface
        if not iface:
            return None
        eth_ip = get_ethernet_ip(iface)
        with self._lock:
            self.status.ethernet_ip = eth_ip
        return eth_ip

    def _reconcile_ethernet(self) -> None:
        """React to ethernet appearing, disappearing, or changing IP.

        Only acts while in a state where the AP is up (BEACON, PORTAL,
        DIRECT) or when CLIENT mode is interrupted. We deliberately do
        NOT yank the AP if the user is mid-onboarding (CONNECTING).
        """
        if self.status.state in (State.CONNECTING, State.AP_STARTING, State.SCANNING):
            return

        new_ip = self._refresh_ethernet_ip()
        current_state = self.status.state

        if new_ip and current_state == State.PORTAL:
            # Ethernet plugged in while a captive-portal was up: switch to
            # BEACON so the SSID advertises the new wired address. The
            # phone stays connected because we keep the same NM profile;
            # only the SSID broadcast changes when we restart the AP.
            log.info("ethernet appeared while in PORTAL — promoting to BEACON")
            self.ap.stop()
            self._enter_beacon_mode(new_ip)
            return

        if new_ip and current_state == State.BEACON:
            expected_ssid = self._ap_ssid(ethernet_ip=new_ip)
            if expected_ssid != self.status.ap_ssid:
                log.info("ethernet IP changed (%s -> %s) — rebroadcasting AP",
                         self.status.ap_ssid, expected_ssid)
                self.ap.stop()
                self._enter_beacon_mode(new_ip)
            return

        if not new_ip and current_state == State.BEACON:
            log.info("ethernet dropped while in BEACON — falling back to WiFi onboarding")
            self.ap.stop()
            self._transition(State.SCANNING, "ethernet lost")
            self._try_known_networks()
            return

    def _check_client_health(self) -> None:
        if not self.client.is_connected():
            log.warning("client connection lost — rescanning")
            self._transition(State.SCANNING, "client connection lost")
            self._try_known_networks()

    def _transition(self, dst: State, detail: str) -> None:
        with self._lock:
            src = self.status.state
            try:
                Transition(src=src, dst=dst).assert_valid()
            except ValueError as exc:
                log.error("blocked transition: %s", exc)
                return
            self.status.state = dst
            self.status.detail = detail
            self.status.history.append(f"{src.value}->{dst.value}: {detail}")
            # Cap history so memory doesn't grow unbounded over a long uptime.
            if len(self.status.history) > 50:
                self.status.history = self.status.history[-50:]
            log.info("state %s -> %s (%s)", src.value, dst.value, detail)
