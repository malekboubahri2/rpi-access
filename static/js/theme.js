// Theme toggle. Cycle: auto -> light -> dark -> auto.
// Persisted in localStorage so the choice survives reloads.
(function () {
  "use strict";

  var KEY = "rpi-access.theme";
  var html = document.documentElement;
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var icon = btn.querySelector(".theme-icon");

  var ORDER = ["auto", "light", "dark"];
  var LABELS = { auto: "A", light: "☀", dark: "☾" };

  function apply(theme) {
    html.setAttribute("data-theme", theme);
    if (icon) {
      icon.textContent = LABELS[theme] || "A";
      icon.setAttribute("data-icon", theme);
    }
    try { localStorage.setItem(KEY, theme); } catch (e) { /* private mode */ }
  }

  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { /* ignore */ }
  apply(stored && ORDER.indexOf(stored) !== -1 ? stored : "auto");

  btn.addEventListener("click", function () {
    var cur = html.getAttribute("data-theme") || "auto";
    var next = ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length];
    apply(next);
  });
})();
