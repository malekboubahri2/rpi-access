// Onboarding workflow: submit connect, poll status, handle Direct Mode.
(function () {
  "use strict";

  var form = document.getElementById("connect-form");
  var ssidInput = document.getElementById("connect-ssid-input");
  var pskInput = document.getElementById("psk");
  var connectBtn = document.getElementById("connect-btn");
  var connectCard = document.getElementById("connect-card");
  var connectErr = document.getElementById("connect-error");
  var directBtn = document.getElementById("direct-btn");
  var banner = document.getElementById("status-banner");
  var bannerText = document.getElementById("status-text");

  function setBusy(btn, busy) {
    if (!btn) return;
    var sp = btn.querySelector(".spinner");
    btn.disabled = !!busy;
    if (sp) sp.hidden = !busy;
  }

  function setBanner(state, detail) {
    if (!banner || !bannerText) return;
    banner.setAttribute("data-state", state);
    bannerText.textContent = detail || state;
  }

  function showError(msg) {
    if (!connectErr) return;
    connectErr.hidden = !msg;
    connectErr.textContent = msg || "";
  }

  async function pollUntilTerminal(expectedSsid) {
    // Poll /api/status until state moves out of "connecting".
    var deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      try {
        var res = await fetch("/api/status", { headers: { Accept: "application/json" } });
        var data = await res.json();
        setBanner(data.state, data.detail);
        if (data.state === "client") {
          showError("");
          renderSuccess(data);
          return;
        }
        if (data.state === "portal" && data.error) {
          showError(data.error);
          setBusy(connectBtn, false);
          return;
        }
        if (data.state === "direct") {
          window.location.assign("/direct");
          return;
        }
      } catch (e) { /* transient — keep polling */ }
      await new Promise(function (r) { setTimeout(r, 1500); });
    }
    showError("Connection attempt timed out. Try again or pick a different network.");
    setBusy(connectBtn, false);
  }

  function renderSuccess(data) {
    // We've left AP mode — the phone may or may not be on the same network as
    // the Pi now, so just give the user a clear message.
    if (connectCard) {
      connectCard.innerHTML =
        '<h2>Connected!</h2>' +
        '<p class="muted">The device joined <strong>' + escapeHtml(data.ssid || "the network") +
        '</strong> at <code>' + escapeHtml(data.ip_address || "—") + '</code>. ' +
        'You may need to reconnect your phone to your usual WiFi.</p>';
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  if (form) {
    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      showError("");
      var ssid = ssidInput.value.trim();
      var psk = pskInput.value;
      if (!ssid) {
        showError("Pick a network first.");
        return;
      }
      setBusy(connectBtn, true);
      setBanner("connecting", "Requesting connection to " + ssid);
      try {
        var res = await fetch("/api/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ ssid: ssid, psk: psk })
        });
        var data = await res.json();
        if (!res.ok || !data.ok) {
          showError(data.error || "Could not start connection.");
          setBusy(connectBtn, false);
          return;
        }
      } catch (err) {
        showError("Request failed. Check that you're still connected to the device's WiFi.");
        setBusy(connectBtn, false);
        return;
      }
      pollUntilTerminal(ssid);
    });
  }

  if (directBtn) {
    directBtn.addEventListener("click", async function () {
      setBusy(directBtn, true);
      try {
        await fetch("/api/direct", { method: "POST" });
        window.location.assign("/direct");
      } catch (e) {
        showError("Could not switch to Direct Mode. Try again.");
        setBusy(directBtn, false);
      }
    });
  }

  // Reflect current state on first load.
  fetch("/api/status").then(function (r) { return r.json(); }).then(function (d) {
    setBanner(d.state, d.detail);
  }).catch(function () { /* ignore */ });
})();
