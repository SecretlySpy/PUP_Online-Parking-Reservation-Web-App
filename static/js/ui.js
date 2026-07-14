/* Global UI behaviors — dependency-free, progressive enhancement.
 * Everything degrades gracefully: with JS off, the nav still shows (CSS),
 * messages still render (server-side), and forms still submit.
 *
 *   1. Theme toggle (light/dark) with localStorage persistence.
 *   2. Mobile hamburger navigation.
 *   3. Dismissible, auto-hiding flash "toasts".
 *   4. Confirmation prompts for destructive actions via data-confirm.
 */
(function () {
  "use strict";

  // --- 1. Theme toggle -------------------------------------------------------
  var themeBtn = document.querySelector("[data-theme-toggle]");
  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function effectiveTheme() {
    return document.documentElement.getAttribute("data-theme") ||
      (systemPrefersDark() ? "dark" : "light");
  }
  function paintThemeIcon() {
    if (themeBtn) themeBtn.textContent = effectiveTheme() === "dark" ? "☀️" : "🌙";
  }
  if (themeBtn) {
    paintThemeIcon();
    themeBtn.addEventListener("click", function () {
      var next = effectiveTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) { /* private mode */ }
      paintThemeIcon();
    });
  }

  // --- 2. Mobile navigation --------------------------------------------------
  var navToggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (navToggle && nav) {
    function closeNav() {
      nav.classList.remove("is-open");
      navToggle.setAttribute("aria-expanded", "false");
    }
    navToggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    // Close after choosing a destination or pressing Escape.
    nav.addEventListener("click", function (e) { if (e.target.closest("a")) closeNav(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeNav(); });
  }

  // --- 3. Toast messages -----------------------------------------------------
  function dismiss(alert) {
    alert.classList.add("is-hiding");
    setTimeout(function () { alert.remove(); }, 300);
  }
  document.querySelectorAll("#messages .alert").forEach(function (alert) {
    var close = alert.querySelector(".alert__close");
    if (close) close.addEventListener("click", function () { dismiss(alert); });
    // Auto-hide only positive/neutral notices; keep errors/warnings until read.
    if (/alert--success|alert--info/.test(alert.className)) {
      setTimeout(function () { dismiss(alert); }, 6000);
    }
  });

  // --- 4. Confirm destructive actions ---------------------------------------
  // A submit button (or link) carrying data-confirm="..." prompts before acting.
  document.addEventListener("submit", function (e) {
    var msg = null;
    if (e.submitter && e.submitter.hasAttribute("data-confirm")) {
      msg = e.submitter.getAttribute("data-confirm");
    } else if (e.target.hasAttribute("data-confirm")) {
      msg = e.target.getAttribute("data-confirm");
    }
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);
  document.addEventListener("click", function (e) {
    var link = e.target.closest("a[data-confirm]");
    if (link && !window.confirm(link.getAttribute("data-confirm"))) e.preventDefault();
  });
})();
