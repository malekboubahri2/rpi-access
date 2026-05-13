"""Flask blueprint — onboarding UI and JSON API.

The blueprint is wired to a `BootOrchestrator` (or a stub for
`--portal-only`) via the app config key ``orchestrator``. All mutating
endpoints push the request into the orchestrator's queue and return
immediately; the UI polls `/api/status` for progress.
"""
from __future__ import annotations

from typing import Protocol

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)

from rpi_access.core.exceptions import ValidationError, WifiError
from rpi_access.core.logger import get_logger
from rpi_access.core.state import State
from rpi_access.security.validator import validate_psk, validate_ssid

log = get_logger(__name__)


class OrchestratorLike(Protocol):
    def request_connect(self, ssid: str, psk: str | None) -> None: ...
    def request_direct_mode(self) -> None: ...
    def request_retry(self) -> None: ...
    def request_rescan(self) -> None: ...
    def snapshot(self) -> object: ...

    # WiFi scanner — exposed for the cached-results endpoint.
    scanner: object


def _get_orchestrator() -> OrchestratorLike:
    orch = current_app.config.get("orchestrator")
    if orch is None:
        abort(503, description="Orchestrator not available")
    return orch  # type: ignore[return-value]


def build_blueprint() -> Blueprint:
    bp = Blueprint("portal", __name__)

    # ------- HTML pages ----------------------------------------------------------

    @bp.route("/", methods=["GET"])
    def onboarding() -> str:
        orch = _get_orchestrator()
        snap = orch.snapshot()
        return render_template(
            "onboarding.html",
            state=snap.state.value,
            detail=snap.detail,
            ap_ssid=snap.ap_ssid,
            ethernet_ip=snap.ethernet_ip,
        )

    @bp.route("/direct", methods=["GET"])
    def direct_mode_page() -> str:
        orch = _get_orchestrator()
        snap = orch.snapshot()
        return render_template(
            "direct_mode.html",
            ap_ssid=snap.ap_ssid,
            ethernet_ip=snap.ethernet_ip,
        )

    # ------- JSON API ------------------------------------------------------------

    @bp.route("/api/status", methods=["GET"])
    def api_status():
        orch = _get_orchestrator()
        snap = orch.snapshot()
        return jsonify({
            "state": snap.state.value,
            "detail": snap.detail,
            "ssid": snap.ssid,
            "ap_ssid": snap.ap_ssid,
            "ip_address": snap.ip_address,
            "ethernet_ip": snap.ethernet_ip,
            "error": snap.error,
            "is_terminal": snap.state in (State.CLIENT, State.DIRECT, State.BEACON, State.STOPPED),
        })

    @bp.route("/api/networks", methods=["GET"])
    def api_networks():
        """Return nearby WiFi networks.

        Calls `nmcli device wifi list` (unscoped — see scanner.py for the
        reason). That query is cheap even while the AP is up because NM
        serves it from its global scan cache, so we run it inline.
        If the call fails we fall back to whatever the orchestrator's
        last successful scan cached.
        """
        orch = _get_orchestrator()
        scanner = getattr(orch, "scanner", None)
        if scanner is None:
            log.warning("api_networks: scanner unavailable")
            return jsonify({"networks": [], "error": "scanner unavailable"}), 503
        try:
            nets = scanner.scan()
            cached, cached_at = scanner.cached()
            log.info("api_networks: scan returned %d networks (cache=%d, at=%.0f)",
                     len(nets), len(cached), cached_at)
            return jsonify({
                "networks": [n.to_dict() for n in nets],
                "cached_at": cached_at,
            })
        except WifiError as exc:
            log.warning("api_networks: live scan failed (%s); serving cache", exc)
            cached, cached_at = scanner.cached()
            return jsonify({
                "networks": [n.to_dict() for n in cached],
                "cached_at": cached_at,
                "error": str(exc),
                "stale": True,
            })
        except Exception as exc:  # noqa: BLE001 — surface any unexpected error
            log.exception("api_networks: unexpected failure: %s", exc)
            return jsonify({
                "networks": [],
                "error": f"{type(exc).__name__}: {exc}",
            }), 500

    @bp.route("/api/connect", methods=["POST"])
    def api_connect():
        orch = _get_orchestrator()
        payload = request.get_json(silent=True) or request.form
        try:
            ssid = validate_ssid(str(payload.get("ssid", "")))
            psk = validate_psk(payload.get("psk"))
        except ValidationError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        orch.request_connect(ssid, psk)
        return jsonify({"ok": True, "ssid": ssid})

    @bp.route("/api/retry", methods=["POST"])
    def api_retry():
        orch = _get_orchestrator()
        orch.request_retry()
        return jsonify({"ok": True})

    @bp.route("/api/rescan", methods=["POST"])
    def api_rescan():
        """Queue a force-rescan. On a Pi this briefly drops the AP.

        Returns immediately; the cache (and `/api/networks`) updates
        after ~10-20 s. The phone will momentarily disconnect from the
        AP and reconnect automatically.
        """
        orch = _get_orchestrator()
        orch.request_rescan()
        return jsonify({"ok": True, "warning": "AP will briefly drop"})

    @bp.route("/api/direct", methods=["POST"])
    def api_direct():
        orch = _get_orchestrator()
        orch.request_direct_mode()
        return jsonify({"ok": True})

    @bp.route("/api/health", methods=["GET"])
    def api_health():
        return jsonify({"ok": True})

    return bp
