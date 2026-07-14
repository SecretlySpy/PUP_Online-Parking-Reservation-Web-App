/* Shared live-polling for the customer slot view and the admin monitor.
 * Replaces the two near-identical inline scripts. Progressive enhancement:
 * the grid is server-rendered, so with JS off it still works (just static).
 *
 * Contract (set on the container element):
 *   class="live-poll"
 *   data-poll-endpoint="<fragment url>"   required
 *   data-poll-interval="10000"            optional (ms)
 *   data-poll-form="<form id>"            optional — serialise filters
 * An optional sibling `[data-poll-status-for="<container id>"]` receives
 * "Updating…", cleared on success, or an error notice on failure.
 */
(function () {
  "use strict";

  function initPoll(el) {
    var endpoint = el.dataset.pollEndpoint;
    if (!endpoint) return;
    var interval = parseInt(el.dataset.pollInterval || "10000", 10);
    var form = el.dataset.pollForm ? document.getElementById(el.dataset.pollForm) : null;
    var status = el.id ? document.querySelector('[data-poll-status-for="' + el.id + '"]') : null;
    var timer = null;

    function query() {
      return form ? new URLSearchParams(new FormData(form)).toString() : "";
    }
    function setStatus(text, isError) {
      if (!status) return;
      status.textContent = text;
      status.classList.toggle("poll-status--error", !!isError);
    }
    async function refresh() {
      setStatus("Updating…", false);
      try {
        var qs = query();
        var resp = await fetch(endpoint + (qs ? "?" + qs : ""), {
          headers: { "X-Requested-With": "fetch" },
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        el.innerHTML = await resp.text();
        setStatus("", false); // the fragment shows its own "updated HH:MM:SS"
      } catch (e) {
        setStatus("Couldn't refresh — will retry", true); // keep last good render
      }
    }

    // Instant refresh when filters change (no full page reload).
    if (form) {
      form.addEventListener("change", refresh);
      form.addEventListener("submit", function (e) { e.preventDefault(); refresh(); });
    }

    function start() {
      if (!timer) {
        timer = setInterval(function () { if (!document.hidden) refresh(); }, interval);
      }
    }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    // Pause polling on hidden/backgrounded tabs; catch up on return.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { stop(); } else { refresh(); start(); }
    });
    start();
  }

  document.querySelectorAll(".live-poll[data-poll-endpoint]").forEach(initPoll);
})();
