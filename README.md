# rpi-access

> Production-grade WiFi onboarding & fallback connectivity for Raspberry Pi.

rpi-access turns a fresh Raspberry Pi into a headless, self-onboarding edge
device. On boot it will try to reach known WiFi networks; if none are
reachable it transparently switches to **Access Point** mode and exposes a
mobile-friendly **captive portal** for the user to enter new credentials. It
can also be told to stay in **Direct Mode** — keeping the AP up indefinitely
so the device is reachable over SSH at `user@192.168.4.1`.

The stack is intentionally boring and Linux-native:

- Python 3.11 + Flask
- NetworkManager / `nmcli` (no manual `wpa_supplicant.conf` edits)
- `dnsmasq` for captive DNS (when not handled by NetworkManager shared mode)
- `systemd` for lifecycle management

---

## Features

| Area              | Capability                                                            |
|-------------------|-----------------------------------------------------------------------|
| Boot orchestration| State machine — `boot → scan → connect → ap_fallback → portal → ok`   |
| WiFi              | Scan, save, prioritise, auto-reconnect known networks                 |
| Access Point      | `rpi-access-XXXX` SSID, `192.168.4.1/24`, WPA2 or open                  |
| Captive Portal    | Apple/Android probe URLs handled, fallback `http://192.168.4.1`       |
| Onboarding UI     | Responsive, dark/light, password reveal, retry flow                   |
| Direct Mode       | Keep AP, allow SSH-only operation                                     |
| Security          | Input validation, encrypted credential store, no plaintext logging    |
| Observability     | Rotating logs, healthcheck, journald integration                      |
| Deployment        | One-command `setup.sh`, systemd services, idempotent install          |

---

## Quick Start

```bash
git clone https://github.com/<you>/rpi-access.git
cd rpi-access
sudo ./setup.sh
sudo systemctl status rpi-access
```

That's it. On the next boot the Pi will either join a known network or
broadcast `rpi-access-XXXX`. Connect from a phone, open any HTTP URL, and the
captive portal will appear.

Manual portal URL: <http://192.168.4.1>

---

## Repository Layout

```text
rpi-access/
├── README.md
├── LICENSE
├── .gitignore
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── setup.sh                  # one-command installer
├── uninstall.sh              # clean removal
├── config/
│   ├── rpi-access.conf    # main config (INI)
│   ├── hostapd.conf          # AP fallback (only used if NM unavailable)
│   ├── dnsmasq.conf          # DNS redirect for captive portal
│   └── systemd/
│       ├── rpi-access.service
│       └── rpi-access-portal.service
├── scripts/
│   ├── ap_start.sh
│   ├── ap_stop.sh
│   └── healthcheck.sh
├── src/rpi_access/                # Python package (underscore for import)
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                # Flask factory
│   ├── core/
│   │   ├── boot.py           # state machine orchestrator
│   │   ├── state.py          # State enum + transitions
│   │   ├── config.py         # config loader
│   │   ├── logger.py         # logging setup
│   │   └── exceptions.py     # custom exceptions
│   ├── wifi/
│   │   ├── scanner.py        # nmcli wifi scan parser
│   │   ├── client.py         # nmcli connection management
│   │   └── ap.py             # AP lifecycle
│   ├── portal/
│   │   ├── routes.py         # Flask blueprint
│   │   └── captive.py        # probe-URL handlers
│   └── security/
│       ├── validator.py      # SSID/PSK validation
│       └── credentials.py    # encrypted credentials store
├── templates/                # Jinja2 templates
├── static/                   # CSS / JS / images
├── tests/                    # pytest suite
└── docs/
    ├── architecture.md
    ├── boot_flow.md
    ├── api.md
    └── troubleshooting.md
```

---

## How It Works — TL;DR

```
┌──────────┐  ┌───────────┐  ┌────────────┐  ┌──────────────┐  ┌────────┐
│  Boot    │->│ Scan WiFi │->│ Try known  │->│ AP fallback  │->│ Portal │
│ (systemd)│  │ (nmcli)   │  │ networks   │  │ (NM hotspot) │  │ (Flask)│
└──────────┘  └───────────┘  └─────┬──────┘  └──────┬───────┘  └───┬────┘
                                   │ ok               │ creds      │
                                   ▼                  ▼ saved      │
                              ┌──────────┐      ┌──────────────────▼─────┐
                              │ Client   │◄─────│ Retry connect          │
                              │ mode     │  ok  │ (loop until success or │
                              └──────────┘      │ user picks Direct Mode)│
                                                └────────────────────────┘
```

Full sequence: [docs/boot_flow.md](docs/boot_flow.md)
Module diagram: [docs/architecture.md](docs/architecture.md)
REST API: [docs/api.md](docs/api.md)

---

## Configuration

Edit `/etc/rpi-access/rpi-access.conf` after install. The file is INI:

```ini
[network]
ap_ssid_prefix   = rpi-access
ap_password      =                 ; empty = open AP, set for WPA2 (>=8 chars)
ap_gateway       = 192.168.4.1
ap_subnet        = 192.168.4.0/24
ap_dhcp_start    = 192.168.4.10
ap_dhcp_end      = 192.168.4.100
wifi_interface   = wlan0
scan_timeout_s   = 15
connect_timeout_s= 25
connect_retries  = 3

[portal]
host             = 0.0.0.0
port             = 80
secret_key_file  = /etc/rpi-access/secret.key

[security]
credentials_file = /etc/rpi-access/credentials.enc
key_file         = /etc/rpi-access/master.key

[logging]
level            = INFO
file             = /var/log/rpi-access/rpi-access.log
max_bytes        = 1048576
backups          = 5
```

Restart with `sudo systemctl restart rpi-access`.

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Tests
pytest

# Lint
ruff check src tests

# Run portal only (no AP setup, no root needed)
RPI_ACCESS_DEV=1 python -m rpi_access --portal-only
```

Unit tests do **not** touch real WiFi — `nmcli` is mocked. See `tests/`.

---

## Git Workflow

- `main` — protected, deploys cleanly to a Pi.
- `develop` — integration branch.
- `feat/*`, `fix/*`, `docs/*`, `chore/*` — short-lived topic branches.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).
- PRs require: tests green, ruff clean, no plaintext secrets in diff.

Suggested initial commit ordering: [docs/architecture.md#commit-plan](docs/architecture.md#commit-plan).

---

## Deployment Checklist

- [ ] Raspberry Pi OS **Bookworm** (NetworkManager is default — verify with `nmcli -v`).
- [ ] `wlan0` is not rfkill-blocked: `rfkill list wifi`.
- [ ] `setup.sh` ran without error and `systemctl is-enabled rpi-access` returns `enabled`.
- [ ] Reboot, observe AP appears within ~30 s if no known SSID is in range.
- [ ] Phone connects to `rpi-access-XXXX`, captive portal pops automatically.
- [ ] After credentials saved: device reboots to client mode within ~20 s.

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md). Common things:

| Symptom                         | Likely cause                                          |
|---------------------------------|-------------------------------------------------------|
| AP never appears                | Country code unset → `sudo raspi-config` → Localisation |
| Portal not auto-launching       | Phone caches captive state — toggle WiFi              |
| Connect succeeds, AP still up   | `rpi-access.service` failed mid-transition — check `journalctl -u rpi-access` |
| `nmcli` errors `Not authorized` | Service not running as root / missing polkit         |

---

## Roadmap

See [docs/architecture.md#future-improvements](docs/architecture.md#future-improvements).

---

## License

MIT — see [LICENSE](LICENSE).
