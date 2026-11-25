/* Driving mode — page controller (DOM, GPS, map, voice, vibration, Wake Lock, data refresh).
 * All decisions (heading, ahead/behind, stages, de-duplication) live in the pure drive-engine.js.
 * Privacy: the driver's track never leaves the device. Hazard lists are requested with a position
 * rounded to ~1 km, sent in a POST body (never in the URL, so it is not in server logs); nothing
 * about the trip is stored.
 * Security: every report text is rendered with textContent (never innerHTML).
 */
(function () {
  "use strict";
  const IR = window.IR, G = window.IRGeo, E = window.IRDriveEngine;
  const root = document.querySelector("main.dv");
  const cfgEl = document.getElementById("drive-config");
  if (!root || !cfgEl || !G || !E) return;

  const CFG = JSON.parse(cfgEl.textContent);
  // refetch distance from the server: keeps the far-alert distance ahead inside the fetched circle
  const REFRESH_DIST_M = CFG.refresh_dist_m > 0 ? CFG.refresh_dist_m : 1000;
  const RETRY_MS = 30000;              // retry delay after a failed refresh
  const TICK_MS = 15000;               // status bar / periodic refresh check
  const COORD_DECIMALS = 2;            // ≈1.1 km: the server never receives the exact position
  const APPROX_MAX_AGE_MS = 300000;    // a quick position up to 5 min old is fine for placing the map
  const SLOW_FIX_HINT_S = 20;          // after this many seconds without a fix, explain the likely cause
  const SEV_COLORS = { high: "#c0392b", medium: "#e2a73e", low: "#6fb5a8" };
  const ICON_RE = /^bi-[a-z0-9-]+$/;
  const numFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

  /* ---------- i18n ---------- */
  const S = CFG.i18n || {};
  function t(key, vars) {
    let s = S[key] != null ? S[key] : IR.t(key);
    if (vars) Object.keys(vars).forEach((k) => { s = s.split("{" + k + "}").join(String(vars[k])); });
    return s;
  }
  function fmtDistance(m, spoken) {
    const d = E.roundDistance(m);
    const unit = d.unit === "km" ? (spoken ? t("spokenKm") : t("unitKm")) : (spoken ? t("spokenM") : t("unitM"));
    return numFmt.format(d.value) + " " + unit;
  }

  /* ---------- DOM ---------- */
  const $ = (sel) => root.querySelector(sel);
  const ui = {
    start: $('[data-action="start"]'), stop: $('[data-action="stop"]'), recenter: $('[data-action="recenter"]'),
    intro: $("[data-intro]"), message: $("[data-message]"), list: $("[data-list]"),
    bannerIcon: $("[data-banner-icon]"), bannerTitle: $("[data-banner-title]"), bannerMeta: $("[data-banner-meta]"),
    bannerDist: $("[data-banner-dist]"),
    gps: $('[data-status="gps"] span'), data: $('[data-status="data"] span'), net: $('[data-status="net"] span'),
    netItem: $('[data-status="net"]'), itemTpl: document.getElementById("dvItemTpl"),
  };
  const noHazardText = ui.bannerTitle.textContent;

  // key identifies the message so a condition can clear its own message when it is over
  const TRANSIENT = new Set(["gps", "heading", "outside"]);
  function showMessage(text, tone, key) {
    ui.message.hidden = !text;
    ui.message.textContent = text || "";
    ui.message.dataset.tone = tone || "info";
    ui.message.dataset.key = key || "";
  }
  function clearMessage(keys) {
    if (keys.has(ui.message.dataset.key)) showMessage("");
  }

  /* ---------- engine & trip state ---------- */
  const engine = E.createEngine({
    farM: CFG.far_m, nearM: CFG.near_m, coneDeg: CFG.cone_deg, bbox: CFG.libya_bbox,
  });
  const trip = { active: false, id: 0, source: null, lastFetch: null, fetching: false, fetchedAt: null, summaryDone: false,
                 lastPos: null, wakeLock: null, timer: null, audio: null, follow: true, fetchError: false };

  /* ---------- map ---------- */
  let map = null, driverMarker = null, hazardLayer = null;
  function initMap() {
    if (map || !window.L) return;
    const box = CFG.libya_bbox;
    map = L.map("driveMap", { zoomControl: false, attributionControl: true })
      .setView([(box.min_lat + box.max_lat) / 2, (box.min_lng + box.max_lng) / 2], 6);
    L.tileLayer(CFG.tiles, { maxZoom: 18, attribution: CFG.attribution }).addTo(map);
    hazardLayer = L.layerGroup().addTo(map);
    map.on("dragstart", () => { trip.follow = false; ui.recenter.hidden = !trip.active; });
  }
  function popupFor(h) {
    const el = document.createElement("div");
    const b = document.createElement("strong"); b.textContent = h.category.name; el.appendChild(b);
    const s = document.createElement("div"); s.textContent = h.severity.name + (h.km_label ? " · " + h.km_label : ""); el.appendChild(s);
    return el;
  }
  function drawHazards(items) {
    if (!hazardLayer) return;
    hazardLayer.clearLayers();
    items.forEach((h) => L.circleMarker([h.lat, h.lng], {
      radius: 9, color: "#fff", weight: 2, fillColor: SEV_COLORS[h.severity.code] || "#999", fillOpacity: 0.95,
    }).bindPopup(popupFor(h)).addTo(hazardLayer));
  }
  function drawDriver(pos) {
    if (!map) return;
    const ll = [pos.lat, pos.lng];
    if (!driverMarker) {
      driverMarker = L.circleMarker(ll, { radius: 10, color: "#fff", weight: 3, fillColor: "#34668e", fillOpacity: 1 }).addTo(map);
    } else driverMarker.setLatLng(ll);
    if (trip.follow) map.setView(ll, Math.max(map.getZoom(), 14), { animate: true });
  }

  /* ---------- status bar ---------- */
  function renderNet() {
    const on = navigator.onLine;
    ui.net.textContent = on ? t("online") : t("offline");
    ui.netItem.dataset.tone = on ? "ok" : "bad";
  }
  function renderDataAge() {
    if (!trip.fetchedAt) { ui.data.textContent = t("notUpdated"); return; }
    const min = Math.floor((Date.now() - trip.fetchedAt) / 60000);
    ui.data.textContent = min < 1 ? t("updatedJustNow") : t("updatedMinutes", { n: min });
  }
  function renderGps(accuracy) {
    ui.gps.textContent = accuracy == null ? t("gpsWaiting") : t("gpsAccuracy", { n: Math.round(accuracy) });
  }

  /* ---------- banner & list ---------- */
  function setIcon(el, icon) { el.className = "bi " + (ICON_RE.test(icon || "") ? icon : "bi-exclamation-triangle-fill"); }
  function renderBanner(row) {
    if (!row) {
      ui.bannerIcon.className = "bi bi-shield-check";
      ui.bannerTitle.textContent = noHazardText;
      ui.bannerMeta.textContent = ""; ui.bannerDist.textContent = "";
      return;
    }
    const h = row.hazard;
    setIcon(ui.bannerIcon, h.category.icon);
    ui.bannerTitle.textContent = h.category.name;
    ui.bannerMeta.textContent = h.severity.name + (h.km_label ? " · " + h.km_label : "");
    ui.bannerDist.textContent = fmtDistance(row.distanceM);
  }
  function renderList(rows) {
    const frag = document.createDocumentFragment();
    rows.slice(1).forEach((r) => {
      const li = ui.itemTpl.content.firstElementChild.cloneNode(true);
      setIcon(li.querySelector(".dv-item-ico i"), r.hazard.category.icon);
      li.querySelector(".dv-item-title").textContent = r.hazard.category.name;
      li.querySelector(".dv-item-meta").textContent = r.hazard.severity.name;
      li.querySelector(".dv-item-dist").textContent = fmtDistance(r.distanceM);
      li.dataset.severity = r.hazard.severity.code;
      frag.appendChild(li);
    });
    ui.list.replaceChildren(frag);
  }

  /* ---------- feedback: sound, speech, vibration, notifications ---------- */
  function beep(count) {
    const ctx = trip.audio;
    if (!ctx) return;
    for (let i = 0; i < count; i++) {
      const osc = ctx.createOscillator(), gain = ctx.createGain(), at = ctx.currentTime + i * 0.25;
      osc.frequency.value = count > 1 ? 1046 : 880;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.35, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(at); osc.stop(at + 0.2);
    }
  }
  function speak(text, urgent) {
    if (!("speechSynthesis" in window) || !text) return;
    if (urgent) window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const lang = IR.lang === "en" ? "en" : "ar";
    u.lang = lang === "ar" ? "ar-SA" : "en-US";
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang && v.lang.toLowerCase().startsWith(lang));
    if (voice) u.voice = voice;
    u.rate = 1;
    window.speechSynthesis.speak(u);
  }
  function vibrate(pattern) { try { if (navigator.vibrate) navigator.vibrate(pattern); } catch (e) { /* unsupported */ } }
  async function notify(body, tag, urgent) {
    try {
      if (!("Notification" in window) || Notification.permission !== "granted" || !("serviceWorker" in navigator)) return;
      const reg = await navigator.serviceWorker.getRegistration();
      if (!reg) return;
      await reg.showNotification(t("notificationTitle"), {
        body, tag, renotify: !!urgent, lang: IR.lang, dir: IR.dir, silent: false,
        icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-72.png", data: { url: "/drive" },
      });
    } catch (e) { /* notifications are best-effort */ }
  }
  function flash() {
    root.classList.remove("dv-flash"); void root.offsetWidth; root.classList.add("dv-flash");
  }
  function fireAlert(a) {
    const h = a.hazard;
    const near = a.stage === "near";
    const text = near
      ? t("alertNear", { category: h.category.name, distance: fmtDistance(a.distanceM, true) })
      : t("alertFar", { category: h.category.name, distance: fmtDistance(a.distanceM, true), severity: h.severity.name });
    beep(near ? 3 : 1);
    speak(text, near);
    vibrate(near ? [400, 150, 400, 150, 400] : [250]);
    flash();
    if (document.visibilityState !== "visible") notify(text, "drive-" + a.id + "-" + a.stage, near);
  }

  /* ---------- wake lock ---------- */
  async function acquireWakeLock() {
    if (!("wakeLock" in navigator)) { IR.toast(t("wakeLockUnsupported"), null, null, 8000); return; }
    try {
      trip.wakeLock = await navigator.wakeLock.request("screen");
      trip.wakeLock.addEventListener("release", () => { trip.wakeLock = null; });
    } catch (e) { IR.toast(t("wakeLockUnsupported"), null, null, 8000); }
  }
  function releaseWakeLock() { if (trip.wakeLock) trip.wakeLock.release().catch(() => {}); trip.wakeLock = null; }
  document.addEventListener("visibilitychange", () => {
    if (trip.active && document.visibilityState === "visible" && !trip.wakeLock) acquireWakeLock();
  });

  /* ---------- hazards (network) ---------- */
  function round(v) { const f = 10 ** COORD_DECIMALS; return Math.round(v * f) / f; }
  async function fetchHazards(pos) {
    if (trip.fetching) return;
    trip.fetching = true;
    const tripId = trip.id; // a response that arrives after this trip ended is ignored
    const current = () => trip.active && trip.id === tripId;
    const radius = Math.min(50, CFG.fetch_radius_km + 2); // +2 km compensates the rounded position
    const body = { lat: round(pos.lat), lng: round(pos.lng), radius_km: radius };
    try {
      const r = await IR.api(CFG.endpoint, { method: "POST", json: body });
      if (!current()) return;
      if (!r.ok || !r.data || !r.data.ok) throw new Error("http " + r.status);
      const items = r.data.data.items;
      engine.setHazards(items);
      drawHazards(items);
      trip.lastFetch = { at: Date.now(), pos };
      trip.fetchedAt = Date.now();
      trip.fetchError = false;
      clearMessage(new Set(["data"]));
      if (!trip.summaryDone) tripSummary(items.length);
    } catch (e) {
      if (!current()) return;
      trip.fetchError = true;
      // keep the last list; retry soon instead of waiting for the full refresh interval
      trip.lastFetch = { at: Date.now() - CFG.refresh_s * 1000 + RETRY_MS, pos: (trip.lastFetch && trip.lastFetch.pos) || pos };
      showMessage(t("updateFailed"), "warn", "data");
    } finally {
      if (trip.id === tripId) { trip.fetching = false; renderDataAge(); }
    }
  }
  function maybeRefresh(pos) {
    if (pos && E.shouldRefresh(trip.lastFetch, Date.now(), pos, CFG.refresh_s * 1000, REFRESH_DIST_M)) fetchHazards(pos);
  }
  function tripSummary(n) {
    trip.summaryDone = true;
    const text = n > 0 ? t("tripSummary", { n, radius: CFG.fetch_radius_km }) : t("tripSummaryNone", { radius: CFG.fetch_radius_km });
    showMessage(text, "info", "summary");
    speak(text);
    notify(text, "drive-summary");
  }

  /* ---------- GPS ---------- */
  function toFix(p) {
    const c = p.coords;
    return { lat: c.latitude, lng: c.longitude, accuracy: c.accuracy, heading: c.heading, speed: c.speed, timestamp: p.timestamp };
  }
  /**
   * Accurate fixes come from a high-accuracy watch (they drive the alerts). A first GPS fix can take
   * from seconds to minutes (cold start, indoors, computers without GPS), so a quick low-accuracy /
   * recently cached position is also requested: it only places the map and loads the hazards early.
   */
  function gpsSource() {
    let id = null;
    return {
      start(onFix, onError, onApprox) {
        if (!window.isSecureContext) { onError({ code: "insecure" }); return; }
        if (!("geolocation" in navigator)) { onError({ code: "unsupported" }); return; }
        id = navigator.geolocation.watchPosition((p) => onFix(toFix(p)), onError,
          { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
        navigator.geolocation.getCurrentPosition((p) => onApprox(toFix(p)), () => {},
          { enableHighAccuracy: false, maximumAge: APPROX_MAX_AGE_MS, timeout: 15000 });
      },
      stop() { if (id != null) navigator.geolocation.clearWatch(id); id = null; },
    };
  }

  /* While no accurate fix has arrived: elapsed time, then the most likely reason. */
  function renderWaiting() {
    if (!trip.active || trip.gotFix) return;
    const secs = Math.round((Date.now() - trip.waitStart) / 1000);
    let text;
    if (trip.gpsUnavailable) text = t("gpsUnavailable");
    else if (trip.approx) text = t("gpsApprox", { n: Math.round(trip.approx.accuracy) }); // permission already given
    else if (trip.permission === "prompt") text = IR.t("locatingHint");
    else text = t("gpsWaitingFor", { n: secs });
    if (secs >= SLOW_FIX_HINT_S && !trip.gpsUnavailable) text += " " + t("gpsSlowHint");
    showMessage(text, trip.gpsUnavailable ? "bad" : "warn", "gps");
  }
  function startWaiting() {
    Object.assign(trip, { gotFix: false, approx: null, gpsUnavailable: false, permission: null, waitStart: Date.now() });
    clearInterval(trip.waitTimer);
    trip.waitTimer = setInterval(renderWaiting, 1000);
    renderWaiting();
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: "geolocation" }).then((p) => {
        trip.permission = p.state;
        p.onchange = () => { trip.permission = p.state; renderWaiting(); };
        renderWaiting();
      }).catch(() => {});
    }
  }
  function stopWaiting() { clearInterval(trip.waitTimer); trip.waitTimer = null; }

  function onApprox(fix) {
    if (!trip.active || trip.gotFix || !G.validPoint(fix)) return;
    trip.approx = fix;
    const pos = { lat: fix.lat, lng: fix.lng };
    ui.gps.textContent = t("gpsApproxShort", { n: Math.round(fix.accuracy) });
    drawDriver(pos);
    if (G.inBox(pos, CFG.libya_bbox)) { trip.lastPos = pos; maybeRefresh(pos); }
    renderWaiting();
  }

  function onGpsError(err) {
    const code = err && err.code;
    const fatal = { 1: "locationDenied", insecure: "locationInsecure", unsupported: "locationUnsupported" }[code];
    if (fatal) { stop(); showMessage(IR.t(fatal), "bad", "fatal"); return; }
    // 2 = position unavailable (location services off / no source), 3 = timeout: keep watching
    if (code === 2) trip.gpsUnavailable = true;
    if (!trip.gotFix) renderWaiting();
    else showMessage(t("gpsWaiting"), "warn", "gps");
  }

  function onFix(fix) {
    if (!trip.active) return;
    if (!trip.gotFix) { trip.gotFix = true; trip.gpsUnavailable = false; stopWaiting(); clearMessage(new Set(["gps"])); }
    const s = engine.update(fix);
    renderGps(Number.isFinite(fix.accuracy) ? fix.accuracy : null);
    if (s.status === "invalid") return;
    if (s.status === "weak_gps") {
      showMessage(t("gpsWeak", { n: Math.round(fix.accuracy) }), "warn", "gps");
      root.dataset.stage = "none";
      return;
    }
    trip.lastPos = s.position;
    drawDriver(s.position);
    if (s.status === "outside") {
      showMessage(t("outsideLibya"), "warn", "outside");
      root.dataset.stage = "none";
      renderBanner(null); renderList([]);
      return;
    }
    maybeRefresh(s.position);
    renderBanner(s.upcoming[0]);
    renderList(s.upcoming);
    if (s.status === "no_heading") {
      clearMessage(new Set(["gps", "outside"]));
      showMessage(t("headingUnknown"), "info", "heading");
      root.dataset.stage = "none";
      return;
    }
    clearMessage(TRANSIENT);
    root.dataset.stage = (s.upcoming[0] && s.upcoming[0].stage) || "none";
    s.alerts.forEach(fireAlert);
  }

  /* ---------- start / stop ---------- */
  function setState(active) {
    root.dataset.state = active ? "driving" : "idle";
    ui.start.hidden = active; ui.stop.hidden = !active; ui.intro.hidden = active;
    ui.recenter.hidden = true;
    root.querySelectorAll("[data-hide-when-driving]").forEach((el) => { el.hidden = active; });
  }
  async function start() {
    if (trip.active) return;
    initMap();
    engine.reset();
    Object.assign(trip, { active: true, id: trip.id + 1, fetching: false, lastFetch: null, fetchedAt: null,
                          summaryDone: false, lastPos: null, follow: true, fetchError: false });
    setState(true);
    renderGps(null); renderDataAge(); renderNet();
    startWaiting();
    try { // audio must be unlocked inside the user gesture
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC && !trip.audio) trip.audio = new AC();
      if (trip.audio && trip.audio.state === "suspended") trip.audio.resume();
    } catch (e) { trip.audio = null; }
    if ("speechSynthesis" in window) window.speechSynthesis.getVoices(); // warm up the voice list
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
    acquireWakeLock();
    trip.source = CFG.simulate && window.IRDriveSim ? window.IRDriveSim.create(CFG, { geo: G, notice: (m) => showMessage(m, "info") }) : gpsSource();
    trip.source.start(onFix, onGpsError, onApprox);
    trip.timer = setInterval(() => { renderDataAge(); if (trip.lastPos) maybeRefresh(trip.lastPos); }, TICK_MS);
  }
  function stop() {
    if (!trip.active) return;
    trip.active = false;
    trip.fetching = false; // an in-flight request belongs to the ended trip and is ignored on arrival
    if (trip.source) trip.source.stop();
    trip.source = null;
    clearInterval(trip.timer);
    stopWaiting();
    releaseWakeLock();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    engine.reset();
    root.dataset.stage = "none";
    setState(false);
    renderBanner(null); renderList([]);
    if (hazardLayer) hazardLayer.clearLayers();
    showMessage(t("tripEnded"), "info", "ended");
  }

  ui.start.addEventListener("click", start);
  ui.stop.addEventListener("click", stop);
  ui.recenter.addEventListener("click", () => {
    trip.follow = true; ui.recenter.hidden = true;
    if (trip.lastPos) drawDriver(trip.lastPos);
  });
  window.addEventListener("online", renderNet);
  window.addEventListener("offline", renderNet);
  window.addEventListener("pagehide", stop);

  setState(false);
  renderNet();
  renderGps(null);
  renderDataAge();
  initMap();
})();
