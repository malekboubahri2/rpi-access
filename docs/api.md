# HTTP API

The portal exposes a small JSON API for the onboarding UI and external
provisioning tools. All endpoints are reachable only while the device
is in `AP_STARTING`, `PORTAL`, or `DIRECT` state — once the orchestrator
hands `wlan0` to the upstream network, the portal is no longer routable
from the AP subnet.

Base URL during onboarding: `http://192.168.4.1`

## `GET /`

Renders the onboarding UI. HTML. Not part of the JSON API.

## `GET /direct`

Renders the Direct Mode confirmation page. HTML.

## `GET /api/status`

Current orchestrator state. Polled by the UI every 1.5 s during a
connect attempt.

**Response (200)**

```json
{
  "state": "portal",
  "detail": "captive portal serving",
  "ssid": null,
  "ap_ssid": "rpi-access-A1B2",
  "ip_address": null,
  "error": null,
  "is_terminal": false
}
```

`state` is one of: `boot`, `scanning`, `connecting`, `client`,
`ap_starting`, `portal`, `direct`, `error`, `stopped`.

`is_terminal` is `true` for `client`, `direct`, `stopped` — UIs can
stop polling once that flips.

## `GET /api/networks`

Triggers a fresh scan and returns visible networks, strongest signal
first.

**Response (200)**

```json
{
  "networks": [
    {
      "ssid": "Home WiFi",
      "signal": 82,
      "security": "WPA2",
      "frequency": 2412,
      "in_use": false,
      "bssid": "AA:BB:CC:DD:EE:FF",
      "is_open": false
    }
  ]
}
```

**Response (500)**

```json
{ "networks": [], "error": "nmcli failed (rc=1): …" }
```

## `POST /api/connect`

Queue a connection attempt. Returns immediately; the caller should poll
`/api/status` for progress.

**Request**

```json
{ "ssid": "Home WiFi", "psk": "supersecret" }
```

`psk` may be `""` or absent for open networks. SSIDs are validated
against IEEE 802.11 (1–32 octets, no NUL/control chars). PSKs must be
8–63 printable ASCII chars or 64 hex digits.

**Response (200)**

```json
{ "ok": true, "ssid": "Home WiFi" }
```

**Response (400)**

```json
{ "ok": false, "error": "Password must be 8-63 ASCII chars or 64 hex digits." }
```

## `POST /api/retry`

Re-enter `SCANNING` and try known networks again. No body required.

**Response (200)**

```json
{ "ok": true }
```

## `POST /api/direct`

Enter Direct Mode — keep the AP up indefinitely.

**Response (200)**

```json
{ "ok": true }
```

## `GET /api/health`

Liveness probe (does not touch nmcli). Returns 200 as long as the
portal thread is responsive.

```json
{ "ok": true }
```

## Captive probe redirects

Every URL not matched by the routes above receives a `302 Found` to
`/`. This is how the phone's OS detects the captive portal and pops the
native overlay automatically. Probe URLs known to be handled by this
behaviour:

| Path                              | Vendor    |
|-----------------------------------|-----------|
| `/generate_204`, `/gen_204`      | Google / Android |
| `/hotspot-detect.html`           | Apple |
| `/library/test/success.html`     | Apple older |
| `/connecttest.txt`, `/ncsi.txt`  | Microsoft |
| `/canonical.html`                | Firefox |

## Error responses

| Status | When                                            |
|--------|-------------------------------------------------|
| 400    | Validation failed (bad SSID or PSK)              |
| 404    | API path doesn't exist                           |
| 500    | Internal error (nmcli unreachable, parse failed) |
| 503    | Orchestrator not attached (only in dev mode)     |
