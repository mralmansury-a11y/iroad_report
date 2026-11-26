/* Driving mode — page controller (DOM, GPS, map, voice, vibration, Wake Lock, data refresh).
 * All decisions (heading, ahead/behind, stages, de-duplication) live in the pure drive-engine.js.
 *
 * Offline: the full list of verified hazards in Libya is downloaded (GET /reports/alertable, no position)
 * and saved on the device (offline-store.js). Alerts, the driver's position and the route therefore keep
 * working without internet; when online the list is checked every refresh_s (ETag → 304, almost no data).
 * Viewed map tiles are kept by the service worker; the road line is drawn as a vector even without tiles.
 * Privacy: the position and the route never leave the device; the route is kept in memory only.
 * Security: every report text is rendered with textContent (never innerHTML).
 */
(function () {
  "use strict";
  const IR = window.IR, G = window.IRGeo, E = window.IRDriveEngine;
  const root = document.querySelector("main.dv");
  const cfgEl = document.getElementById("drive-config");
  if (!root || !cfgEl || !G || !E) return;

  const CFG = JSON.parse(cfgEl.textContent);
  const STORE_KEY = "drive-hazards";  // offline copy of the verified-hazard list
  const RETRY_MS = 30000;              // retry delay after a failed refresh
  const TICK_MS = 15000;               // status bar / periodic refresh check
  const TRACK_STEP_M = 15;             // route: minimum distance between two recorded points
  const TRACK_MAX_POINTS = 20000;      // route: older points are thinned above this
  const APPROX_MAX_AGE_MS = 300000;    // a quick position up to 5 min old is fine for placing the map
  const SLOW_FIX_HINT_S = 20;          // after this many seconds without a fix, explain the likely cause
  const SEV_COLORS = { high: "#c0392b", medium: "#e2a73e", low: "#6fb5a8" };
  const LIST_EXTRA = 2;                // hazards listed under the banner (kept short while driving)
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
    bannerIcon: $("[data-banner-icon]"), bannerTitle: $("[data-banner-title]"), bannerDist: $("[data-banner-dist]"),
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
    listRadiusM: CFG.fetch_radius_km * 1000, // the saved list covers Libya: show only the configured radius
  });
  const trip = { active: false, source: null, summaryDone: false, lastPos: null, wakeLock: null, timer: null,
                 audio: null, follow: true };
  // verified hazards kept on the device; shared by every trip on this page
  const data = { items: [], etag: null, fetchedAt: null, loaded: false, syncing: false, lastTry: 0, failed: false };
  const track = []; // driver's route of the current trip (memory only)

  /* ---------- map ---------- */
  let map = null, driverMarker = null, hazardLayer = null, trackLine = null;
  function initMap() {
    if (map || !window.L) return;
    const box = CFG.libya_bbox;
    // canvas renderer: the whole national hazard list can be drawn without slowing the page
    map = L.map("driveMap", { zoomControl: false, attributionControl: true, preferCanvas: true })
      .setView([(box.min_lat + box.max_lat) / 2, (box.min_lng + box.max_lng) / 2], 6);
    // crossOrigin → CORS tiles the service worker can keep for offline use (never opaque responses)
    L.tileLayer(CFG.tiles, { maxZoom: 18, attribution: CFG.attribution, crossOrigin: true }).addTo(map);
    drawRoad();
    trackLine = L.polyline([], { color: "#1f6fb2", weight: 6, opacity: 0.85, interactive: false }).addTo(map);
    hazardLayer = L.layerGroup().addTo(map);
    map.on("dragstart", () => { trip.follow = false; ui.recenter.hidden = !trip.active; });
  }
  /* The road as a vector line: visible even where no map tile is saved (served from the SW data cache offline). */
  async function drawRoad() {
    if (!CFG.road_endpoint) return;
    try {
      const r = await IR.api(CFG.road_endpoint);
      const pts = (r.ok && r.data && r.data.data && r.data.data.polyline) || [];
      if (map && pts.length > 1) {
        L.polyline(pts.map((p) => [p[0], p[1]]), { color: "#0e6e76", weight: 6, opacity: 0.6, interactive: false })
          .addTo(map).bringToBack();
      }
    } catch (e) { /* the road line is optional */ }
  }
  function addTrackPoint(pos) {
    const before = track.length;
    if (!E.appendTrack(track, pos, TRACK_STEP_M, TRACK_MAX_POINTS) || !trackLine) return;
    if (track.length === before + 1) trackLine.addLatLng([pos.lat, pos.lng]);
    else trackLine.setLatLngs(track.map((p) => [p.lat, p.lng])); // older part was thinned
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
      radius: 11, color: "#fff", weight: 3, fillColor: SEV_COLORS[h.severity.code] || "#999", fillOpacity: 1,
    }).bindPopup(popupFor(h)).addTo(hazardLayer));
  }
  function drawDriver(pos) {
    if (!map) return;
    const ll = [pos.lat, pos.lng];
    if (!driverMarker) {
      driverMarker = L.circleMarker(ll, { radius: 12, color: "#fff", weight: 4, fillColor: "#1f6fb2", fillOpacity: 1 }).addTo(map);
    } else driverMarker.setLatLng(ll);
    if (trip.follow) map.setView(ll, Math.max(map.getZoom(), 14), { animate: true });
  }

  /* ---------- status bar ---------- */
  /* Status chips are short (icon + a few characters); the full sentence is the chip's tooltip / label. */
  function chip(li, text, full) { li.textContent = text; li.parentElement.title = full || text; }
  function renderNet() {
    const on = navigator.onLine;
    ui.net.textContent = on ? t("online") : t("offline"); // visually hidden: the icon colour carries it
    ui.netItem.title = ui.net.textContent;
    ui.netItem.dataset.tone = on ? "ok" : "bad";
  }
  function renderDataAge() {
    if (!data.fetchedAt) { chip(ui.data, "—", t("notUpdated")); return; }
    const min = Math.floor((Date.now() - data.fetchedAt) / 60000);
    let full, short;
    if (min < 1) { full = t("updatedJustNow"); short = t("ageNow"); }
    else if (min < 60) { full = t("updatedMinutes", { n: min }); short = t("ageMinutes", { n: min }); }
    else if (min < 48 * 60) { const n = Math.floor(min / 60); full = t("updatedHours", { n }); short = t("ageHours", { n }); }
    else { const n = Math.floor(min / 1440); full = t("updatedDays", { n }); short = t("ageDays", { n }); }
    chip(ui.data, short, full);
  }
  function renderGps(accuracy) {
    if (accuracy == null) chip(ui.gps, "…", t("gpsWaiting"));
    else chip(ui.gps, "±" + Math.round(accuracy) + " " + t("unitM"), t("gpsAccuracy", { n: Math.round(accuracy) }));
  }

  /* ---------- banner & list ---------- */
  function setIcon(el, icon) { el.className = "bi " + (ICON_RE.test(icon || "") ? icon : "bi-exclamation-triangle-fill"); }
  function renderBanner(row) {
    if (!row) {
      ui.bannerIcon.className = "bi bi-shield-check";
      ui.bannerTitle.textContent = noHazardText;
      ui.bannerDist.textContent = "";
      return;
    }
    const h = row.hazard;
    setIcon(ui.bannerIcon, h.category.icon);
    ui.bannerTitle.textContent = h.category.name;
    ui.bannerDist.textContent = fmtDistance(row.distanceM);
  }
  function renderList(rows) {
    const frag = document.createDocumentFragment();
    rows.slice(1, 1 + LIST_EXTRA).forEach((r) => {
      const li = ui.itemTpl.content.firstElementChild.cloneNode(true);
      setIcon(li.querySelector(".dv-item-ico i"), r.hazard.category.icon);
      li.querySelector(".dv-item-title").textContent = r.hazard.category.name;
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

  /* ---------- hazards: offline copy + background sync ---------- */
  function applyHazards() {
    engine.setHazards(data.items);
    drawHazards(data.items);
    maybeSummary();
  }
  async function loadSaved() {
    const saved = window.IRStore ? await window.IRStore.get(STORE_KEY) : null;
    if (saved && Array.isArray(saved.items) && !data.loaded) {
      Object.assign(data, { items: saved.items, etag: saved.etag || null, fetchedAt: saved.fetchedAt || null, loaded: true });
      applyHazards();
      renderDataAge();
    }
  }
  function save() {
    if (window.IRStore) window.IRStore.set(STORE_KEY, { items: data.items, etag: data.etag, fetchedAt: data.fetchedAt });
  }
  /** Download the list when it changed (If-None-Match → 304 costs almost nothing). Never sends a position. */
  async function syncHazards() {
    if (data.syncing || !CFG.hazards_endpoint) return;
    data.syncing = true;
    data.lastTry = Date.now();
    try {
      const headers = { Accept: "application/json", "X-Requested-With": "fetch" };
      if (data.etag && data.loaded) headers["If-None-Match"] = data.etag;
      const res = await fetch(CFG.hazards_endpoint, { credentials: "same-origin", headers, cache: "no-store" });
      if (res.status === 304) {
        data.fetchedAt = Date.now();
      } else {
        const body = res.ok ? await res.json() : null;
        if (!body || !body.ok) throw new Error("http " + res.status);
        Object.assign(data, { items: body.data.items, etag: res.headers.get("ETag"), fetchedAt: Date.now(), loaded: true });
        applyHazards();
      }
      data.failed = false;
      save();
      clearMessage(new Set(["data"]));
    } catch (e) {
      data.failed = true; // keep the saved list; retry soon
      if (!data.loaded) showMessage(t("noSavedReports"), "warn", "data");
      else if (trip.active) showMessage(navigator.onLine ? t("updateFailed") : t("usingSaved", { n: data.items.length }), "info", "data");
    } finally {
      data.syncing = false;
      renderDataAge();
    }
  }
  function maybeSync() {
    if (Date.now() - data.lastTry >= (data.failed ? RETRY_MS : CFG.refresh_s * 1000)) syncHazards();
  }
  /* Spoken summary once per trip, computed on the device from the saved list. */
  function maybeSummary() {
    if (!trip.active || trip.summaryDone || !data.loaded || !trip.lastPos) return;
    tripSummary(E.countWithin(data.items, trip.lastPos, CFG.fetch_radius_km * 1000));
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
    if (G.inBox(pos, CFG.libya_bbox)) { trip.lastPos = pos; maybeSummary(); }
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
    addTrackPoint(s.position);
    maybeSummary();
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
    Object.assign(trip, { active: true, summaryDone: false, lastPos: null, follow: true });
    applyHazards(); // engine.reset() emptied its list: give it the saved one again
    track.length = 0;
    if (trackLine) trackLine.setLatLngs([]);
    if (!data.loaded && !navigator.onLine) showMessage(t("noSavedReports"), "warn", "data");
    data.lastTry = 0; // check for a newer list now
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
    maybeSync();
    trip.timer = setInterval(() => { renderDataAge(); maybeSync(); }, TICK_MS);
  }
  function stop() {
    if (!trip.active) return;
    trip.active = false;
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
    showMessage(t("tripEnded"), "info", "ended");
  }

  ui.start.addEventListener("click", start);
  ui.stop.addEventListener("click", stop);
  ui.recenter.addEventListener("click", () => {
    trip.follow = true; ui.recenter.hidden = true;
    if (trip.lastPos) drawDriver(trip.lastPos);
  });
  window.addEventListener("online", () => { renderNet(); data.lastTry = 0; maybeSync(); });
  window.addEventListener("offline", renderNet);
  window.addEventListener("pagehide", stop);

  setState(false);
  renderNet();
  renderGps(null);
  renderDataAge();
  initMap();
  // saved list first (works offline), then a check for a newer one so it is ready before the trip
  loadSaved().then(maybeSync);
})();
