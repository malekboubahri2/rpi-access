# Troubleshooting

Most issues fall into four buckets: NetworkManager state, country code,
permissions, and stale profiles. Walk through this in order.

## Step 1 — Check the service

```bash
systemctl status rpi-access
journalctl -u rpi-access -n 200 --no-pager
```

State transitions are logged as
`state <src> -> <dst> (<reason>)`. The most recent transition tells you
where the orchestrator got stuck.

## Step 2 — Check NetworkManager itself

```bash
nmcli -v
systemctl is-active NetworkManager
nmcli -t -f STATE general
nmcli -t -f DEVICE,STATE device
```

`STATE` should be `connected` (CLIENT mode) or `disconnected` followed
by an active AP profile (PORTAL mode). If `wlan0` reports `unmanaged`,
NM has been told not to touch it — usually via
`/etc/NetworkManager/conf.d/*.conf`. Remove the override and reload:

```bash
sudo grep -l 'wlan0' /etc/NetworkManager/conf.d/*.conf
sudo systemctl restart NetworkManager
```

## Step 3 — Check rfkill

A surprising number of "AP doesn't appear" reports come down to a soft
rfkill block left over from `raspi-config`.

```bash
rfkill list wifi
sudo rfkill unblock wifi
```

## Step 4 — Set the country code

WiFi regulatory domain affects which channels are usable. If it's
unset, NM may refuse to bring up an AP at all.

```bash
sudo raspi-config nonint do_wifi_country GB     # or your two-letter code
sudo iw reg get
```

## Step 5 — Inspect saved profiles

```bash
nmcli -t -f NAME,TYPE,DEVICE connection show
```

Look for:

* `rpi-access-AP` — the orchestrator's AP profile. Present in PORTAL,
  absent in CLIENT.
* Any client-mode profile matching the SSID you're trying to join.
  If you see two profiles for the same SSID, delete both and let the
  orchestrator recreate one:

  ```bash
  sudo nmcli connection delete id "<ssid>"
  ```

## Step 6 — Verify config + key files

```bash
ls -l /etc/rpi-access/
# expected: 0600 master.key, 0600 secret.key, 0644 rpi-access.conf
sudo /opt/rpi-access/scripts/healthcheck.sh
```

Exit 0 means the unit's `ExecStartPre` will pass.

## Common symptoms

### AP appears but phone never sees the captive prompt

* Most phones cache "this AP has internet" for ~24 h. Toggle WiFi off/on.
* Confirm DNS is being served: connect a laptop, run `dig example.com @192.168.4.1` — it should return `192.168.4.1`.
* On iOS in particular, the captive prompt only fires for *new* networks. Forgetting the network on the phone forces a fresh probe.

### Connect succeeds, but `/api/status` stays "connecting"

Most likely an APIPA fallback — the SSID accepted us but no DHCP. Check:

```bash
sudo journalctl -u rpi-access | grep "no IP after"
sudo nmcli -t -f IP4.ADDRESS device show wlan0
```

If you see `169.254.x.x`, the upstream router's DHCP pool is exhausted
or the SSID is captive-portal-protected (hotel WiFi etc.). The
orchestrator deletes the broken profile and falls back to AP mode.

### `nmcli` errors with "Not authorized"

The service is running as a non-root user without the right polkit
rules. The shipped unit runs as `root`; don't change that without
adding polkit rules for `org.freedesktop.NetworkManager.network-control`.

### Portal scan list is empty while the AP is up

Cause: `nmcli device wifi list ifname wlan0` returns empty when wlan0
is committed to AP mode. We deliberately do NOT pass `ifname` for the
list query — `nmcli device wifi list` (no scope) serves NM's global
scan cache, which works even in AP mode.

If you see an empty list and a `journalctl -u rpi-access` log line like
`live scan failed; serving cache`, NetworkManager hasn't cached
anything yet. Use the **"Force a full rescan"** link in the portal (or
`POST /api/rescan`) to briefly cycle the AP for a real scan.

To verify by hand while SSH'd in:

```bash
nmcli device wifi list                 # global cache — should show APs
nmcli device wifi list ifname wlan0    # scoped — empty while AP is up
```

### Portal loads but `/api/networks` is empty

Often a kernel-side scan stall. Force a rescan from outside the
process:

```bash
sudo nmcli device wifi rescan ifname wlan0
sudo nmcli -t device wifi list ifname wlan0 | head
```

If `nmcli` returns nothing, restart the wpa supplicant stack:

```bash
sudo systemctl restart NetworkManager
```

### Two DHCP servers fighting

Symptom: clients on the AP get an IP, then lose it a few seconds later.
Cause: `dhcpcd` or a hand-installed `dnsmasq` running alongside NM's
internal stack.

```bash
systemctl status dhcpcd dnsmasq
sudo systemctl disable --now dhcpcd dnsmasq 2>/dev/null || true
sudo systemctl restart NetworkManager rpi-access
```

## Manual fallback recipe (hostapd + dnsmasq)

If NM's `shared` mode is permanently broken on your image, the bundled
`config/hostapd.conf` and `config/dnsmasq.conf` work as a manual AP:

```bash
sudo cp config/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp config/dnsmasq.conf /etc/dnsmasq.d/rpi-access.conf
sudo nmcli device set wlan0 managed no       # let NM go
sudo systemctl restart hostapd dnsmasq
sudo ip addr add 192.168.4.1/24 dev wlan0
```

This is documented for completeness — the supported path is NM shared
mode and the orchestrator does not currently drive these services.

## Where logs live

| Source                  | Location                                  |
|-------------------------|-------------------------------------------|
| Service stdout/stderr   | `journalctl -u rpi-access`                |
| Rotated app log         | `/var/log/rpi-access/rpi-access.log`      |
| NetworkManager debug    | `journalctl -u NetworkManager`            |
| Kernel WiFi events      | `dmesg \| grep -i wlan`                   |

## Getting help

When opening an issue, please include:

* Output of `journalctl -u rpi-access --no-pager -n 200`
* Output of `nmcli -v`, `cat /etc/os-release`
* `nmcli -t -f DEVICE,STATE device`
* The contents of `/etc/rpi-access/rpi-access.conf` (with passwords redacted)
