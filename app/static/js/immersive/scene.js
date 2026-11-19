/* Immersive layer · 3D photo backdrop.
 * Road photographs behind the public interface, always shown at their true aspect ratio:
 *   depth  → two planes (the sharp photo and a blurred ambient copy) move at different
 *            parallax rates with the pointer and the scroll position;
 *   time   → slow camera drift (Ken Burns) and a random cross-fade to another photo.
 * The photo list comes from the markup (`[data-backdrop]`), so content changes need no JS edits.
 * Reduced-motion users get one still, randomly chosen photo. The cycle pauses while the tab is hidden. */
(function () {
  "use strict";

  const TIMING = {
    holdMs: 16000,           // how long a photo stays before the next cross-fade
    fadeMs: 2400,            // cross-fade duration (mirrored in CSS through --ir-backdrop-fade)
  };
  const DEPTH = {
    shiftPx: 14,             // ambient-plane translation for a full pointer sweep (photo plane: see CSS)
    scrollFactor: 0.05,      // vertical drift per scrolled pixel
    maxScrollShiftPx: 60,
    ease: 0.07,              // pointer smoothing (0..1, per frame)
  };
  const KEN_BURNS_ORIGINS = ["50% 40%", "35% 60%", "65% 55%", "50% 70%", "40% 45%", "60% 35%"];
  const LAST_SCENE_KEY = "ir-last-scene";

  const root = document.querySelector("[data-backdrop]");
  if (!root) return;

  const scenes = parseScenes(root);
  if (!scenes.length) return;

  // Road users are often on weak mobile coverage: the photos (~1 MB) are decoration, the report form is not.
  // Data-saver or a 2G/3G-class link → keep the plain themed background and download nothing.
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn && (conn.saveData || /2g|3g/.test(conn.effectiveType || ""))) {
    root.classList.add("is-lite");
    return;
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const store = (window.IR && window.IR.store) || { get: () => null, set: () => false };

  const stage = document.createElement("div");
  stage.className = "ir-backdrop-stage";
  const layers = [createLayer(), createLayer()];
  layers.forEach((layer) => stage.appendChild(layer.el));
  root.prepend(stage);
  root.style.setProperty("--ir-backdrop-fade", TIMING.fadeMs + "ms");

  const state = { current: -1, front: 0, timerId: 0, frameId: 0, pointer: { x: 0, y: 0 }, target: { x: 0, y: 0 } };

  /* ---------- data ---------- */

  function parseScenes(el) {
    try {
      const base = el.dataset.base || "";
      return JSON.parse(el.dataset.scenes || "[]").map((s) => ({ src: base + s.file, focus: s.focus || "50% 50%" }));
    } catch (e) {
      return [];
    }
  }

  function pickNextIndex() {
    if (scenes.length === 1) return 0;
    const avoid = state.current >= 0 ? state.current : store.get(LAST_SCENE_KEY);
    let next;
    do { next = Math.floor(Math.random() * scenes.length); } while (next === avoid);
    return next;
  }

  const randomItem = (list) => list[Math.floor(Math.random() * list.length)];

  /* ---------- layers ---------- */

  function createImage(className) {
    const img = document.createElement("img");
    img.className = className;
    img.alt = "";
    img.decoding = "async";
    return img;
  }

  function createLayer() {
    const el = document.createElement("div");
    el.className = "ir-backdrop-layer";
    const ambient = createImage("ir-backdrop-ambient");
    const photo = createImage("ir-backdrop-photo");
    el.append(ambient, photo);
    return { el, ambient, photo };
  }

  function loadInto(layer, scene) {
    layer.ambient.src = scene.src;
    layer.photo.src = scene.src;
    layer.photo.style.objectPosition = scene.focus;
    layer.el.style.setProperty("--ir-kb-origin", randomItem(KEN_BURNS_ORIGINS));
    return layer.photo.decode ? layer.photo.decode().catch(() => undefined) : Promise.resolve();
  }

  async function showScene(index) {
    const incoming = layers[1 - state.front];
    const outgoing = layers[state.front];
    await loadInto(incoming, scenes[index]);

    incoming.el.classList.remove("is-leaving");
    incoming.el.classList.add("is-active");
    outgoing.el.classList.replace("is-active", "is-leaving");
    window.setTimeout(() => outgoing.el.classList.remove("is-leaving"), TIMING.fadeMs);

    state.front = 1 - state.front;
    state.current = index;
    store.set(LAST_SCENE_KEY, index);
  }

  /* ---------- cycle (time axis) ---------- */

  function scheduleNext() {
    window.clearTimeout(state.timerId);
    if (reducedMotion.matches || document.hidden || scenes.length < 2) return;
    state.timerId = window.setTimeout(async () => {
      await showScene(pickNextIndex());
      scheduleNext();
    }, TIMING.holdMs);
  }

  /* ---------- parallax (depth axis) ---------- */

  function applyDepth() {
    const p = state.pointer;
    p.x += (state.target.x - p.x) * DEPTH.ease;
    p.y += (state.target.y - p.y) * DEPTH.ease;
    const scrollShift = Math.min(window.scrollY * DEPTH.scrollFactor, DEPTH.maxScrollShiftPx);
    stage.style.setProperty("--ir-bd-x", (-p.x * DEPTH.shiftPx).toFixed(2) + "px");
    stage.style.setProperty("--ir-bd-y", (-p.y * DEPTH.shiftPx - scrollShift).toFixed(2) + "px");

    const settled = Math.abs(state.target.x - p.x) < 0.001 && Math.abs(state.target.y - p.y) < 0.001;
    state.frameId = settled ? 0 : requestAnimationFrame(applyDepth);
  }

  function requestDepthFrame() {
    if (!state.frameId) state.frameId = requestAnimationFrame(applyDepth);
  }

  function onPointerMove(event) {
    state.target.x = (event.clientX / window.innerWidth) * 2 - 1;
    state.target.y = (event.clientY / window.innerHeight) * 2 - 1;
    requestDepthFrame();
  }

  /* ---------- wiring ---------- */

  function enableMotion() {
    if (reducedMotion.matches) return;
    // Mouse / trackpad only. On phones the scroll-linked drift moved the photo on every scrolled frame
    // (on top of the browser bar resizing the viewport), which read as the background "refreshing".
    // Touch devices keep a still photo plus the slow Ken Burns drift and cross-fade.
    if (!finePointer.matches) return;
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("scroll", requestDepthFrame, { passive: true });
  }

  document.addEventListener("visibilitychange", scheduleNext);
  reducedMotion.addEventListener("change", scheduleNext);

  showScene(pickNextIndex()).then(() => root.classList.add("is-ready"));
  enableMotion();
  scheduleNext();
})();
