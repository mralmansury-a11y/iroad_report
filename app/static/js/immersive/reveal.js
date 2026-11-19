/* Immersive layer · scroll reveal (3D rise-in as content enters the viewport).
 * Only blocks that start BELOW the fold are prepared, so nothing visible ever flashes;
 * content above the fold is animated by the CSS page-entrance instead. */
(function () {
  "use strict";

  const SELECTOR = ".ir-titlebar, .ir-ann, .ir-card, .ir-cta, .ir-section-title, .ir-item, .ir-menu, .ir-notif, .ir-empty";
  const STAGGER_MS = 70;
  const MAX_STAGGER_STEPS = 6;
  const OBSERVER_OPTIONS = { rootMargin: "0px 0px -6% 0px", threshold: 0.08 };

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) return;

  const isInContent = (el) => Boolean(el.closest("main"));
  const isOutermostTarget = (el) => !el.parentElement.closest(SELECTOR);
  const isBelowFold = (el) => el.getBoundingClientRect().top > window.innerHeight;

  function settle(el) {
    el.classList.remove("ir-reveal", "is-revealed");
    el.style.removeProperty("--ir-reveal-delay");
  }

  function reveal(el) {
    el.addEventListener("transitionend", function onEnd(event) {
      if (event.target !== el || event.propertyName !== "transform") return;
      el.removeEventListener("transitionend", onEnd);
      settle(el);
    });
    el.classList.add("is-revealed");
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(({ isIntersecting, target }) => {
      if (!isIntersecting) return;
      observer.unobserve(target);
      reveal(target);
    });
  }, OBSERVER_OPTIONS);

  const siblingsSeen = new Map();
  document.querySelectorAll(SELECTOR).forEach((el) => {
    if (!isInContent(el) || !isOutermostTarget(el) || !isBelowFold(el)) return;
    const step = siblingsSeen.get(el.parentElement) || 0;
    siblingsSeen.set(el.parentElement, step + 1);
    el.style.setProperty("--ir-reveal-delay", Math.min(step, MAX_STAGGER_STEPS) * STAGGER_MS + "ms");
    el.classList.add("ir-reveal");
    observer.observe(el);
  });
})();
