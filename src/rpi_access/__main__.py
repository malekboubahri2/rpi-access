"""rpi-access CLI entry point.

Two ways to invoke:

    python -m rpi_access                 # full boot orchestrator
    python -m rpi_access --portal-only   # Flask only, no nmcli calls

The full orchestrator is what systemd runs. `--portal-only` exists for
local development on machines without NetworkManager (e.g. a laptop).
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
from typing import NoReturn

from rpi_access import __version__
from rpi_access.core.boot import BootOrchestrator
from rpi_access.core.config import load_config
from rpi_access.core.logger import setup_logging, get_logger


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rpi-access",
        description="Raspberry Pi WiFi onboarding orchestrator + captive portal.",
    )
    p.add_argument(
        "--config",
        default=os.environ.get(
            "RPI_ACCESS_CONFIG", "/etc/rpi-access/rpi-access.conf"
        ),
        help="Path to configuration file (default: %(default)s).",
    )
    p.add_argument(
        "--portal-only",
        action="store_true",
        help="Run only the Flask portal (skip nmcli orchestration). Useful for dev.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended nmcli commands without executing them.",
    )
    p.add_argument("--version", action="version", version=f"rpi_access {__version__}")
    return p


def _install_signal_handlers(orchestrator: BootOrchestrator | None) -> None:
    """Forward SIGTERM / SIGINT into a clean orchestrator shutdown."""
    log = get_logger(__name__)

    def _handler(signum: int, _frame: object) -> None:
        log.info("received signal %s — shutting down", signum)
        if orchestrator is not None:
            orchestrator.request_stop()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main(argv: list[str] | None = None) -> NoReturn:  # type: ignore[misc]
    args = _build_argparser().parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.logging)
    log = get_logger(__name__)

    log.info("rpi-access %s starting (portal_only=%s, dry_run=%s)",
             __version__, args.portal_only, args.dry_run)

    if args.portal_only:
        # Direct Flask serve, no orchestrator. We import lazily so importers
        # don't pay the Flask cost when running the orchestrator path.
        from rpi_access.app import create_app
        app = create_app(cfg)
        host = cfg.portal.host
        port = cfg.portal.port
        log.info("portal-only mode: serving on %s:%s", host, port)
        app.run(host=host, port=port, debug=False, use_reloader=False)
        sys.exit(0)

    orchestrator = BootOrchestrator(cfg, dry_run=args.dry_run)
    _install_signal_handlers(orchestrator)
    exit_code = orchestrator.run()
    log.info("orchestrator exited with code %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
