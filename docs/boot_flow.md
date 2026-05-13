# Boot Flow

End-to-end sequence from a fresh power-on to a steady client connection.

## Sequence

```
power-on
   │
   ▼
systemd boots → NetworkManager.service starts → rpi-access.service starts
   │
   ▼
healthcheck.sh (ExecStartPre)
   ├─ nmcli present?
   ├─ NM active?
   ├─ /etc/rpi-access/rpi-access.conf readable?
   ├─ wlan0 visible in /sys/class/net?
   └─ /etc/rpi-access/master.key exists?      ──── any fails → systemd error
   │
   ▼
python -m rpi_access  (orchestrator main thread starts)
   │
   ▼
core.boot.BootOrchestrator.run()
   │
   │ State: BOOT
   ▼
ethernet IP present on eth0?
   │
   ├── yes ─▶ AP_STARTING → BEACON
   │            (AP up, SSID = rpi-<dashed eth IP>, e.g. rpi-192-168-1-42)
   │            (Flask portal still serves on 192.168.4.1 for optional WiFi onboarding)
   │            (eth poll every `ethernet_poll_s`; if IP changes → restart AP; if cable
   │             pulled → fall back to SCANNING)
   │
   └── no  ─▶ SCANNING
                  │ nmcli device wifi rescan
   │ nmcli device wifi list -t -f SSID,SIGNAL,SECURITY,FREQ,IN-USE,BSSID
   ▼
Match against CredentialStore.list_known()
   │
   ├── No known SSID in range ─────────────────────────────┐
   │                                                       │
   ▼                                                       │
CONNECTING (one known SSID)                                │
   │ nmcli connection up id <ssid>                         │
   │  (or `device wifi connect <ssid> password <psk>`      │
   │   if no profile exists yet)                           │
   │ wait for IPv4 (skip 169.254.x.x)                      │
   │                                                       │
   ├── success ─▶ CLIENT (steady state, periodic healthcheck)
   │                                                       │
   └── failure ─▶ try next known SSID; if all fail ────────┘
                                                           │
                                                           ▼
                                                     AP_STARTING
                                                           │
                                                           │ nmcli connection add type wifi mode ap ...
                                                           │ ipv4.method shared (NM runs internal DHCP+DNS)
                                                           │ nmcli connection up id rpi-access-AP
                                                           ▼
                                                       (Flask thread spawned)
                                                           ▼
                                                        PORTAL
                                                           │
                                                           │ phone connects to rpi-access-XXXX
                                                           │ phone OS probes captive URL → /generate_204 etc.
                                                           │ /captive blueprint 302s to /
                                                           │ user picks SSID + enters PSK
                                                           │
                                                           ├── POST /api/connect ─▶ CONNECTING ─┐
                                                           │                                    │
                                                           │   ┌─────────── on success ◀────────┤
                                                           │   ▼                                │
                                                           │ AP torn down, profile saved        │
                                                           │ ▼                                  │
                                                           │ CLIENT                             │
                                                           │                                    │
                                                           │   on failure: revive AP, stay      │
                                                           │   in PORTAL with error displayed   │
                                                           │                                    │
                                                           └── POST /api/direct ─▶ DIRECT       │
                                                                                                │
                                                                                                │
                                                                                                ▼
                                                                                          (steady state)
```

## Timings (typical Pi 4 on Bookworm)

| Phase                               | Time      |
|------------------------------------|-----------|
| systemd → orchestrator start       | ~6 s      |
| Initial scan                        | ~3 s      |
| Connect to known SSID (success)     | 4–12 s    |
| Fallback to AP                      | 5–8 s     |
| AP visible to phone                 | +1–3 s    |
| Captive prompt on phone             | +1–4 s    |
| Connect-from-portal → CLIENT        | 8–20 s    |

If the fallback AP does not appear within 30 s of boot, check:

```bash
journalctl -u rpi-access -n 100
rfkill list wifi
nmcli -t -f STATE general
nmcli -t -f DEVICE,STATE device
```

See [troubleshooting.md](troubleshooting.md) for diagnosis recipes.

## What "success" means

`CLIENT` is only entered when:

1. `nmcli connection up` returns exit 0,
2. `ip -4 addr show wlan0` returns a non-link-local IPv4 within
   `connect_timeout_s`.

`169.254.x.x` is treated as failure — that's APIPA, meaning DHCP did not
respond. The orchestrator then deletes the broken profile so a retry
starts clean, and falls back to AP mode.

## What "Direct Mode" means

`DIRECT` is a sticky state for users who never want to onboard the Pi
to upstream WiFi. The AP stays up indefinitely; the captive portal
stays reachable at `http://192.168.4.1`; SSH at `ssh user@192.168.4.1`
keeps working as long as the OS user is set up.

To exit Direct Mode, navigate back to `/` from the portal and pick a
network. Internally this transitions `DIRECT → CONNECTING`.
