# Architecture

`rpi-access` is a single-process Python service that orchestrates the
Raspberry Pi's WiFi state machine and serves a captive portal during
onboarding. This document describes the module layout, the runtime
threading model, and the rationale for the most opinionated choices.

## Module diagram

```
                ┌──────────────────────────────────────────────────────┐
                │  rpi_access  (single Python package, single process) │
                └──────────────────────────────────────────────────────┘

  systemd ▶ __main__.py ──▶ core.boot.BootOrchestrator
                                │
                                │ owns ──▶ wifi.Scanner   (nmcli list)
                                │      ──▶ wifi.WifiClient (nmcli up)
                                │      ──▶ wifi.APManager  (nmcli AP)
                                │      ──▶ security.CredentialStore (Fernet)
                                │
                                │ on AP up ──▶ app.create_app() ──▶ Flask thread
                                │                                       │
                                │                                       ▼
                                │                               portal.routes
                                │                               portal.captive
                                │                                       │
                                │ ◀── request_connect / direct_mode ────┘
                                │     request_retry      (queued, serialised)
                                ▼
                          core.state.State (FSM)
```

### One process, two threads

The orchestrator and the Flask server share a Python process so they can
talk through plain method calls. That avoids a second IPC layer that
would have to be hardened against the same `nmcli` race conditions we
already serialise via the orchestrator's lock.

| Thread          | Owner             | Responsibilities                          |
|-----------------|-------------------|-------------------------------------------|
| main            | `BootOrchestrator`| state machine, all `nmcli` invocations    |
| `rpi-access-portal` | werkzeug      | HTTP serving (threaded=True)              |

Portal request handlers DO NOT call `nmcli` directly. They call
`orchestrator.request_*()`, which appends to a single-slot queue. The
orchestrator picks the request up in its next loop tick and executes it
on its own thread. This guarantees serial access to NetworkManager.

## State machine (`core.state`)

```
   ┌────────┐   ┌──────────┐   ┌────────────┐   ┌────────┐
   │  BOOT  │──▶│ SCANNING │──▶│ CONNECTING │──▶│ CLIENT │◀─┐
   └────────┘   └──────────┘   └──┬─────────┘   └────────┘  │
                     ▲            │ fail                    │
                     │            ▼                         │
                     │      ┌──────────────┐                │
                     │      │ AP_STARTING  │                │ link
                     │      └──┬───────────┘                │ lost
                     │         ▼                            │
                     │      ┌────────┐  user picks   ┌────────┐
                     └──────┤ PORTAL │──direct mode─▶│ DIRECT │
                            └────┬───┘                └────────┘
                                 │ connect
                                 ▼
                          (CONNECTING again)
```

Allowed transitions are encoded in `_ALLOWED`. Illegal transitions are
silently logged and ignored — the state machine is the single source of
truth, so a buggy caller cannot corrupt the device's networking.

### Ethernet "beacon" mode

When a wired link is already serving an IP at boot, the orchestrator
skips WiFi onboarding entirely and brings the AP up in **beacon** mode:
the SSID is rewritten to `rpi-<dashed eth IP>` (e.g.
`rpi-192-168-1-42`). Anyone in physical range can read the Pi's
address off their WiFi list and SSH in over the wired LAN — no mDNS,
no router-admin login, no MAC-table scraping.

The orchestrator polls `ip -4 addr show eth0` every
`ethernet_poll_s` seconds while the AP is up. If the IP changes (DHCP
renewal, cable swap), it tears the AP down and brings a new one up
with the refreshed SSID. If the cable is pulled, it falls back to the
standard SCANNING → onboarding flow.

## Key design choices

### Why NetworkManager-only?

Bookworm ships NetworkManager as the default network stack. Older
recipes that mix `wpa_supplicant`, `dhcpcd`, and `hostapd`/`dnsmasq`
directly tend to fail in subtle ways:

* two DHCP servers race for `wlan0` when the AP is up,
* `wpa_supplicant`'s config file gets overwritten on every onboarding,
* `hostapd` and NM fight over `wlan0` ownership during transitions.

NM's `802-11-wireless.mode=ap` + `ipv4.method=shared` runs an internal
DHCP/DNS stack that's mutually exclusive with client mode on the same
interface, so the transitions are atomic from our point of view.

The `hostapd.conf` / `dnsmasq.conf` files in `config/` are kept as a
documented escape hatch only.

### Why Fernet?

The credential store needs symmetric, authenticated encryption with
key rotation. Fernet (in `cryptography`) is the most boring,
well-audited primitive for that. The on-disk format is:

```
<32-byte base64 key file>  →  /etc/rpi-access/master.key   (0600 root)
<Fernet ciphertext>         →  /etc/rpi-access/credentials.enc (0600 root)
```

The plaintext is a small JSON document; we explicitly chose Fernet over
home-rolling AES-GCM because it includes versioning and timestamp
verification out of the box.

### Why single-process?

Earlier drafts split the orchestrator and portal into two systemd
services that talked over a Unix socket. That added:

* a second auth boundary (so the portal couldn't be hijacked into
  spawning AP commands),
* a serialisation format (JSON over the socket),
* a reconnection-retry layer.

For a device that sees one administrator and one transition, that's
over-engineered. The single-process design uses Python's GIL + an
`RLock` to make the same guarantees with a fraction of the surface area.

## Threat model

The portal is reachable only while the AP is broadcasting on the local
RF channel. That's a deliberate scoping decision:

* No portal endpoint is exposed once the device is in CLIENT mode.
* All `nmcli` calls happen on the orchestrator thread (no command
  injection from request handlers).
* PSKs are validated against IEEE 802.11 limits *before* hitting nmcli.
* PSK values never appear in logs (`_nmcli.py` redacts `redact_index`).

What we explicitly do NOT defend against:

* A physically-present attacker can read `master.key` from the SD card
  — encryption at rest depends on the operator using `dm-crypt` if
  required.
* Anyone on the AP's WPA2 network can probe the portal. Set an
  `ap_password` for any non-trivial deployment.

## Commit plan

Suggested ordering when bringing this repo up for the first time on
GitHub. Each step is a self-contained commit:

```
chore: initialise repository structure
feat(core): add config loader, logger, state machine
feat(wifi): add scanner with nmcli output parsing
feat(security): add validator and Fernet credential store
feat(wifi): add nmcli client and AP manager
feat(portal): add Flask app, captive blueprint, onboarding routes
feat(ui): add responsive templates, dark/light theming, JS workflow
feat(boot): wire orchestrator state machine + portal thread
chore(systemd): add unit, healthcheck, installers
test: add unit tests for validator, scanner, credentials, routes, state
docs: add architecture, boot flow, API, and troubleshooting docs
```

## Branch strategy

```
main      ◀── protected; only fast-forward from develop or release/*
develop   ◀── integration; PRs target this
feat/*    ◀── feature branches
fix/*     ◀── bugfix branches
docs/*    ◀── doc-only changes
chore/*   ◀── infra, dependencies, CI
release/* ◀── short-lived; bumps version, cuts tag
```

Conventional Commits — `feat(scope):`, `fix(scope):`, `docs:`, `test:`,
`chore:`, `refactor:`. Scope is the top-level module (`core`, `wifi`,
`portal`, `ui`, `security`, `boot`).

## Future improvements

| Idea                                        | Why                                                  |
|---------------------------------------------|------------------------------------------------------|
| Multi-band AP (5 GHz)                       | Avoids 2.4 GHz congestion in dense apartments        |
| Enterprise WPA2/3 (802.1x)                  | Common in offices; nmcli supports it natively         |
| QR-code provisioning                        | Skip typing the AP password during onboarding         |
| Saved-network management UI                 | Currently only addable via portal; let users forget   |
| Bluetooth fallback for onboarding           | When WiFi radio is rfkill-blocked                     |
| Prometheus metrics endpoint                 | Visibility into reconnect storms in fleet deploys     |
| OTA self-update                             | `git pull && setup.sh` is fine for one Pi, not 1000   |
