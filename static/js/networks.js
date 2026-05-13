// Networks tab: fetch, render, handle selection.
(function () {
  "use strict";

  var list = document.getElementById("network-list");
  var rescanBtn = document.getElementById("rescan-btn");
  var connectCard = document.getElementById("connect-card");
  var connectSsidLabel = document.getElementById("connect-ssid");
  var connectSsidInput = document.getElementById("connect-ssid-input");
  var pskInput = document.getElementById("psk");
  var pskHint = document.getElementById("psk-hint");
  var cancelBtn = document.getElementById("cancel-btn");

  if (!list) return;

  function setBusy(btn, busy) {
    if (!btn) return;
    var spinner = btn.querySelector(".spinner");
    btn.disabled = !!busy;
    if (spinner) spinner.hidden = !busy;
  }

  function signalBars(signal) {
    if (signal >= 75) return "▮▮▮▮";
    if (signal >= 50) return "▮▮▮▯";
    if (signal >= 25) return "▮▮▯▯";
    return "▮▯▯▯";
  }

  function renderEmpty(msg) {
    list.innerHTML = '<li class="empty">' + escapeHtml(msg) + "</li>";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function render(networks) {
    if (!networks || networks.length === 0) {
      renderEmpty("No networks visible. Try rescanning.");
      return;
    }
    var html = "";
    networks.forEach(function (n) {
      var locked = !n.is_open;
      html +=
        '<li><button type="button" class="network' + (n.in_use ? " in-use" : "") + '"' +
        ' data-ssid="' + escapeHtml(n.ssid) + '"' +
        ' data-open="' + (n.is_open ? "1" : "0") + '">' +
        '<span class="ssid">' + escapeHtml(n.ssid) + "</span>" +
        '<span class="meta">' +
        '<span class="lock" aria-hidden="true">' + (locked ? "🔒" : "🔓") + "</span>" +
        '<span class="bars">' + signalBars(n.signal) + "</span>" +
        "</span></button></li>";
    });
    list.innerHTML = html;
  }

  function selectNetwork(ssid, isOpen) {
    if (!connectCard) return;
    connectCard.classList.remove("hidden");
    connectSsidLabel.textContent = ssid;
    connectSsidInput.value = ssid;
    pskInput.value = "";
    pskInput.required = !isOpen;
    pskInput.placeholder = isOpen ? "(none — open network)" : "Enter network password";
    if (pskHint) {
      pskHint.textContent = isOpen
        ? "This network is open. No password required."
        : "Leave blank only for open networks.";
    }
    pskInput.focus();
    connectCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  list.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".network");
    if (!btn) return;
    selectNetwork(btn.dataset.ssid, btn.dataset.open === "1");
  });

  if (cancelBtn && connectCard) {
    cancelBtn.addEventListener("click", function () {
      connectCard.classList.add("hidden");
    });
  }

  // Password reveal toggle.
  var revealBtn = document.getElementById("psk-reveal");
  if (revealBtn && pskInput) {
    revealBtn.addEventListener("click", function () {
      var hidden = pskInput.type === "password";
      pskInput.type = hidden ? "text" : "password";
      revealBtn.textContent = hidden ? "Hide" : "Show";
    });
  }

  function ageLabel(cachedAtUnix) {
    if (!cachedAtUnix) return "never";
    var secs = Math.max(0, Math.round(Date.now() / 1000 - cachedAtUnix));
    if (secs < 5)   return "just now";
    if (secs < 60)  return secs + "s ago";
    if (secs < 3600) return Math.round(secs / 60) + "m ago";
    return Math.round(secs / 3600) + "h ago";
  }

  function setRescanLabel(cachedAtUnix) {
    if (!rescanBtn) return;
    var label = rescanBtn.querySelector(".label");
    if (label) label.textContent = "Rescan";
    rescanBtn.title = "Last scan: " + ageLabel(cachedAtUnix);
  }

  // The first time the user hits "Rescan" we explain that the AP will
  // drop for a few seconds. localStorage so we don't nag forever.
  function confirmHardRescan() {
    try {
      if (localStorage.getItem("rpi-access.rescanWarned") === "1") return true;
    } catch (e) { /* private mode */ }
    var ok = window.confirm(
      "Rescan will briefly drop this WiFi (~15s) so the Pi can scan. " +
      "Your phone should reconnect automatically. Continue?"
    );
    if (ok) {
      try { localStorage.setItem("rpi-access.rescanWarned", "1"); } catch (e) { /* ignore */ }
    }
    return ok;
  }

  async function loadNetworks() {
    setBusy(rescanBtn, true);
    var hadResults = list.querySelector(".network") !== null;
    if (!hadResults) renderEmpty("Scanning…");
    try {
      var res = await fetch("/api/networks", { headers: { Accept: "application/json" } });
      var data = await res.json();
      if (!res.ok && !data.networks) {
        renderEmpty(data.error || "Scan failed");
        return;
      }
      render(data.networks);
      setRescanLabel(data.cached_at);
    } catch (err) {
      if (!hadResults) renderEmpty("Scan request failed.");
    } finally {
      setBusy(rescanBtn, false);
    }
  }

  // Hard rescan: tells the orchestrator to cycle the AP, then polls
  // /api/networks until the cache timestamp moves forward.
  async function hardRescan() {
    if (!confirmHardRescan()) return;
    setBusy(rescanBtn, true);
    renderEmpty("Cycling AP for a fresh scan — your phone may briefly disconnect…");
    var beforeAt = 0;
    try {
      var preRes = await fetch("/api/networks");
      var preData = await preRes.json();
      beforeAt = preData.cached_at || 0;
      await fetch("/api/rescan", { method: "POST" });
    } catch (e) { /* keep going to polling */ }

    var deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
      await new Promise(function (r) { setTimeout(r, 3000); });
      try {
        var res = await fetch("/api/networks");
        var data = await res.json();
        if ((data.cached_at || 0) > beforeAt) {
          render(data.networks);
          setRescanLabel(data.cached_at);
          setBusy(rescanBtn, false);
          return;
        }
      } catch (e) { /* keep polling */ }
    }
    setBusy(rescanBtn, false);
    renderEmpty("Rescan timed out. Refresh the page when the AP is back.");
  }

  if (rescanBtn) {
    rescanBtn.addEventListener("click", function (ev) {
      // Shift-click → force a hard rescan even if a recent one exists.
      if (ev.shiftKey) { hardRescan(); return; }
      loadNetworks();
    });
    rescanBtn.addEventListener("contextmenu", function (ev) {
      ev.preventDefault();
      hardRescan();
    });
  }

  var hardLink = document.getElementById("hard-rescan-link");
  if (hardLink) {
    hardLink.addEventListener("click", function (ev) {
      ev.preventDefault();
      hardRescan();
    });
  }

  // Initial load.
  loadNetworks();
  // Light auto-refresh in the background, but only while no connect in flight.
  setInterval(function () {
    if (!connectCard || connectCard.classList.contains("hidden")) loadNetworks();
  }, 20000);
})();
