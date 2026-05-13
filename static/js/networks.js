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

  async function loadNetworks() {
    setBusy(rescanBtn, true);
    renderEmpty("Scanning…");
    try {
      var res = await fetch("/api/networks", { headers: { Accept: "application/json" } });
      var data = await res.json();
      if (!res.ok) {
        renderEmpty(data.error || "Scan failed");
        return;
      }
      render(data.networks);
    } catch (err) {
      renderEmpty("Scan request failed.");
    } finally {
      setBusy(rescanBtn, false);
    }
  }

  if (rescanBtn) rescanBtn.addEventListener("click", loadNetworks);
  // Initial load.
  loadNetworks();
  // Light auto-refresh in the background, but only while no connect in flight.
  setInterval(function () {
    if (!connectCard || connectCard.classList.contains("hidden")) loadNetworks();
  }, 20000);
})();
