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
    def snapshot(self) -> object: ...

    # WiFi scanner — exposed for the UI's "Scan" button.
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
        )

    @bp.route("/direct", methods=["GET"])
    def direct_mode_page() -> str:
        orch = _get_orchestrator()
        snap = orch.snapshot()
        return render_template("direct_mode.html", ap_ssid=snap.ap_ssid)

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
            "error": snap.error,
            "is_terminal": snap.state in (State.CLIENT, State.DIRECT, State.STOPPED),
        })

    @bp.route("/api/networks", methods=["GET"])
    def api_networks():
        orch = _get_orchestrator()
        try:
            scanner = getattr(orch, "scanner", None)
            if scanner is None:
                return jsonify({"networks": [], "error": "scanner unavailable"}), 503
            nets = scanner.scan()
        except WifiError as exc:
            log.warning("scan API failed: %s", exc)
            return jsonify({"networks": [], "error": str(exc)}), 500
        return jsonify({"networks": [n.to_dict() for n in nets]})

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

    @bp.route("/api/direct", methods=["POST"])
    def api_direct():
        orch = _get_orchestrator()
        orch.request_direct_mode()
        return jsonify({"ok": True})

    @bp.route("/api/health", methods=["GET"])
    def api_health():
        return jsonify({"ok": True})

    return bp
