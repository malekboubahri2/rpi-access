# rpi-access — agent notes

Project-local guidance. Keep this terse.

## What it is

A single-process Python service that runs on a Raspberry Pi and:

1. Tries to join a known WiFi at boot.
2. Falls back to an Access Point + captive portal for onboarding.
3. If the Pi has wired connectivity, broadcasts a "beacon" SSID
   (`rpi-<dashed eth IP>`) for discovery on the wired LAN.
4. Has a "Direct Mode" sticky state for SSH-only operation.

## Stack

| Layer        | Tool                                          |
|--------------|-----------------------------------------------|
| Language     | Python 3.11                                   |
| Web          | Flask + werkzeug (threaded)                   |
| Network      | NetworkManager / `nmcli` only — no `wpa_supplicant.conf` edits, no `dhcpcd` |
| Crypto       | `cryptography` Fernet (credentials at rest)   |
| Lifecycle    | `systemd` (`rpi-access.service`)              |
| Tests        | `pytest` (no real nmcli touched)              |
| Lint         | `ruff`                                        |

## Layout

```
src/rpi_access/              # Python package (underscore)
  core/                      # config, logger, state machine, exceptions, BootOrchestrator
  wifi/                      # scanner, client, AP manager, eth helper, _nmcli wrapper
  security/                  # validator, Fernet credential store
  portal/                    # Flask blueprint + captive probe blueprint
  app.py                     # Flask factory + thread runner
config/                      # rpi-access.conf, systemd unit, hostapd/dnsmasq fallbacks
scripts/                     # ap_start.sh, ap_stop.sh, healthcheck.sh
templates/, static/          # Jinja + CSS/JS (dark/light themed UI)
tests/                       # pytest (validator, scanner, credentials, state, routes, ap, eth)
docs/                        # architecture, boot_flow, api, troubleshooting
setup.sh / uninstall.sh      # idempotent installers
.claude/rule/commits.md      # commit message guidelines (Conventional Commits)
```

## Conventions

- Python identifier: `rpi_access` (underscore). Brand / paths /
  systemd / SSID prefix: `rpi-access` (hyphen).
- The local user on the Pi is **`user`**, not `pi`. SSH targets:
  `ssh user@192.168.4.1` (AP) or `ssh user@<ethernet-ip>` (wired).
- All `nmcli` calls go through [`wifi/_nmcli.py`](src/rpi_access/wifi/_nmcli.py)
  so dry-run and PSK redaction are honoured uniformly.
- Portal handlers must NOT call `nmcli` directly — push requests into
  the orchestrator queue via `request_connect / request_retry /
  request_direct_mode`.
- Don't add docs files unless the human asks. Don't add comments that
  restate code. Keep files under ~500 lines.
- Commits follow Conventional Commits. See
  [.claude/rule/commits.md](.claude/rule/commits.md).

## State machine (just enough to be useful)

```
BOOT → SCANNING → CONNECTING → CLIENT
            └→ AP_STARTING → PORTAL → CONNECTING → CLIENT
                                  └→ DIRECT
       (ethernet detected at boot or while in PORTAL)
            → AP_STARTING → BEACON
```

Allowed transitions are encoded in [`core/state.py`](src/rpi_access/core/state.py).
Illegal transitions are logged and skipped — never silently accepted.

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                  # unit suite, no nmcli needed
RPI_ACCESS_DEV=1 python -m rpi_access --portal-only --config /dev/null
```

## Deploying

```bash
sudo ./setup.sh
sudo systemctl status rpi-access
journalctl -u rpi-access -f
```

## When making changes

- Touching state? Update [`core/state.py`](src/rpi_access/core/state.py) AND
  [`tests/test_state.py`](tests/test_state.py).
- Touching the orchestrator's external surface? Check
  [`portal/routes.py`](src/rpi_access/portal/routes.py),
  [`docs/api.md`](docs/api.md), and the JS in [`static/js/app.js`](static/js/app.js).
- Touching `nmcli` calls? Make sure PSKs are redacted (`redact_index=`).
- Touching the AP SSID derivation? Update
  [`tests/test_ap.py`](tests/test_ap.py).
- Run `pytest` before committing. `ruff check src tests` is also fast.
