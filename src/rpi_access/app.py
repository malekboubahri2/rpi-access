"""Flask application factory.

The factory is intentionally tiny — all routes live in
`rpi_access.portal.routes` and `rpi_access.portal.captive`. The
factory:

1. Builds the app,
2. Loads the secret key from disk (or env override),
3. Registers blueprints,
4. Installs simple error handlers that produce JSON for `/api/*` paths
   and HTML for everything else.

It also exposes a `run_in_thread` helper used by the orchestrator to
serve the portal alongside the state machine.
"""
from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

from rpi_access.core.config import Config
from rpi_access.core.logger import get_logger
from rpi_access.portal.captive import build_captive_blueprint
from rpi_access.portal.routes import build_blueprint

log = get_logger(__name__)


def _load_secret_key(cfg: Config) -> str:
    env_override = os.environ.get("RPI_ACCESS_SECRET_KEY")
    if env_override:
        return env_override
    path = Path(cfg.portal.secret_key_file)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    # First boot: mint a key and persist it 0600.
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key.encode("utf-8"))
    finally:
        os.close(fd)
    return key


def create_app(cfg: Config, *, orchestrator: Any | None = None) -> Flask:
    """Build the Flask app. `orchestrator` is None only in `--portal-only` mode."""
    static_root = Path(__file__).resolve().parent.parent.parent
    app = Flask(
        __name__,
        static_folder=str(static_root / "static"),
        template_folder=str(static_root / "templates"),
    )

    app.config["SECRET_KEY"] = _load_secret_key(cfg)
    app.config["JSON_SORT_KEYS"] = False
    app.config["orchestrator"] = orchestrator or _DummyOrchestrator()
    app.config["rpi_access_config"] = cfg

    app.register_blueprint(build_blueprint())
    # Captive probe blueprint MUST be registered last — it's a catch-all.
    app.register_blueprint(build_captive_blueprint())

    @app.errorhandler(404)
    def _not_found(_exc):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "not found"}), 404
        return render_template("error.html", code=404, message="Not found"), 404

    @app.errorhandler(500)
    def _server_error(exc):
        log.exception("unhandled: %s", exc)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "internal error"}), 500
        return render_template("error.html", code=500, message="Server error"), 500

    @app.errorhandler(503)
    def _unavailable(exc):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": getattr(exc, "description", "unavailable")}), 503
        return render_template("error.html", code=503, message="Service unavailable"), 503

    log.info("Flask app constructed (orchestrator=%s)",
             "real" if orchestrator else "dummy")
    return app


class _ServerThread(threading.Thread):
    """Run werkzeug's WSGI server in a daemon thread."""

    def __init__(self, app: Flask, host: str, port: int) -> None:
        super().__init__(daemon=True, name="rpi_access-portal")
        # threaded=True lets the UI poll /api/status concurrently with
        # /api/connect — both are needed at the same time.
        self._server = make_server(host, port, app, threaded=True)
        self.ctx = app.app_context()

    def run(self) -> None:
        self.ctx.push()
        try:
            log.info("portal listening on %s:%s",
                     self._server.host, self._server.port)
            self._server.serve_forever()
        finally:
            self.ctx.pop()

    def shutdown(self) -> None:
        log.info("portal shutting down")
        self._server.shutdown()


def run_in_thread(app: Flask, host: str, port: int) -> _ServerThread:
    """Start the portal in a background daemon thread and return its handle."""
    t = _ServerThread(app, host, port)
    t.start()
    return t


class _DummyOrchestrator:
    """Stub used by `--portal-only`. Lets the UI render without nmcli."""

    class _Snap:
        from rpi_access.core.state import State as _State
        state = _State.PORTAL
        detail = "portal-only (dev)"
        ssid = None
        ip_address = None
        error = None
        ap_ssid = "rpi-access-DEV"
        ethernet_ip = None
        history: list[str] = []

    class _Scanner:
        def scan(self):
            return []

        def cached(self):
            return [], 0.0

    scanner = _Scanner()

    def request_connect(self, ssid: str, psk: str | None) -> None:
        log.info("[dummy] connect %s", ssid)

    def request_direct_mode(self) -> None:
        log.info("[dummy] direct mode")

    def request_retry(self) -> None:
        log.info("[dummy] retry")

    def request_rescan(self) -> None:
        log.info("[dummy] rescan")

    def snapshot(self):
        return self._Snap()
