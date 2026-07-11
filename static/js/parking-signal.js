/* Parking signal — an animated red/amber/green light.
 *
 * Repurposed and modernised from the original 2020 static site's inline
 * "trafficLights" script (Sign In / Sign Up pages). Now a self-contained,
 * dependency-free enhancer: it drives any element matching `.parking-signal`
 * that contains `.signal-light[data-color]` children, cycling which light is lit.
 *
 * Why data-driven: the sequence lives in one array so the cadence is easy to
 * tweak, and the effect degrades gracefully — with JS off, CSS shows all three
 * lights dimmed (still a recognisable signal).
 */
(function () {
  "use strict";

  // [durationSeconds, litColor] — a simple stop→go loop.
  var SEQUENCE = [
    [2.0, "red"],
    [1.0, "amber"],
    [2.0, "green"],
    [1.0, "amber"],
  ];

  function drive(signal) {
    var lights = {};
    signal.querySelectorAll(".signal-light").forEach(function (el) {
      lights[el.dataset.color] = el;
    });
    var step = 0;

    function tick() {
      var frame = SEQUENCE[step % SEQUENCE.length];
      var lit = frame[1];
      // Light exactly one lamp per frame; dim the rest.
      Object.keys(lights).forEach(function (color) {
        lights[color].classList.toggle("is-lit", color === lit);
      });
      step += 1;
      setTimeout(tick, frame[0] * 1000);
    }
    tick();
  }

  function init() {
    document.querySelectorAll(".parking-signal").forEach(drive);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
