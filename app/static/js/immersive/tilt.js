/* Immersive layer · pointer-driven 3D tilt with a moving glare.
 * Enabled only for precise, hover-capable pointers and when motion is allowed;
 * touch devices keep the CSS press-depth effects instead. */
(function () {
  "use strict";

  const TARGETS = [
    { selector: ".ir-item, .ir-notif", maxDeg: 5, liftPx: 14 },
    // Form controls (choice tiles, location buttons) are deliberately NOT tilted: a target that moves
    // under the pointer while someone is choosing makes the choice harder, not more delightful.
    { selector: ".ir-cta, .ir-stat", maxDeg: 9, liftPx: 10 },
  ];

  const canTilt = window.matchMedia("(hover: hover) and (pointer: fine)").matches
    && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!canTilt) return;

  const percent = (fraction) => (fraction * 100).toFixed(1) + "%";
  const degrees = (value) => value.toFixed(2) + "deg";

  function enableTilt(el, { maxDeg, liftPx }) {
    let frameId = 0;
    let lastEvent = null;

    function applyTilt() {
      frameId = 0;
      const box = el.getBoundingClientRect();
      const x = (lastEvent.clientX - box.left) / box.width;
      const y = (lastEvent.clientY - box.top) / box.height;
      el.style.setProperty("--ir-tilt-x", degrees((0.5 - y) * 2 * maxDeg));
      el.style.setProperty("--ir-tilt-y", degrees((x - 0.5) * 2 * maxDeg));
      el.style.setProperty("--ir-glare-x", percent(x));
      el.style.setProperty("--ir-glare-y", percent(y));
    }

    function onMove(event) {
      lastEvent = event;
      el.classList.add("is-tilting");
      if (!frameId) frameId = requestAnimationFrame(applyTilt);
    }

    function onLeave() {
      cancelAnimationFrame(frameId);
      frameId = 0;
      el.classList.remove("is-tilting");
    }

    el.classList.add("ir-tilt");
    el.style.setProperty("--ir-tilt-lift", liftPx + "px");
    el.addEventListener("pointermove", onMove, { passive: true });
    el.addEventListener("pointerleave", onLeave);
  }

  TARGETS.forEach((target) =>
    document.querySelectorAll(target.selector).forEach((el) => enableTilt(el, target))
  );
})();
