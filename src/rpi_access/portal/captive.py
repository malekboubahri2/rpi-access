"""Captive-portal probe URL handlers.

Modern phones detect captive portals by hitting a small, well-known URL
and checking the response. We answer those with a redirect to our
onboarding page so the phone's OS pops the captive-portal UI
automatically rather than the user having to open a browser.

Probe URLs covered (as of 2026):

* Apple:    `captive.apple.com/hotspot-detect.html`
* Google:   `connectivitycheck.gstatic.com/generate_204`
* Android:  `clients3.google.com/generate_204`
* Microsoft:`www.msftconnecttest.com/connecttest.txt`
* Mozilla:  `detectportal.firefox.com/canonical.html`
"""
from __future__ import annotations

from flask import Blueprint, Response, redirect, url_for

# Probe URLs we explicitly know about (documented here; the catch-all
# redirects every unmatched path regardless, so this is for reference):
#   /hotspot-detect.html       Apple
#   /library/test/success.html Apple older
#   /generate_204              Google / Android
#   /gen_204                   Google legacy
#   /connecttest.txt           Microsoft
#   /ncsi.txt                  Microsoft NCSI
#   /canonical.html            Firefox
#   /check_network_status.txt  Misc


def build_captive_blueprint() -> Blueprint:
    bp = Blueprint("captive", __name__)

    # `/<path:path>` does NOT match the empty path, so the root `/`
    # is left to the portal blueprint's `onboarding` view.
    @bp.route("/<path:path>", methods=["GET"])
    def catch_all(path: str) -> Response:
        # Every unmatched URL (probe or otherwise) gets a 302 to the
        # onboarding page. Phones detect this pattern and pop the
        # native captive-portal overlay automatically.
        _ = path  # marker for ruff; we redirect unconditionally
        return redirect(url_for("portal.onboarding", _external=False), code=302)

    return bp
