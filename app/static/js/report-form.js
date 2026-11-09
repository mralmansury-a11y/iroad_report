/* Report form: location via GPS or map only, image previews, local drafts, honest offline handling. */
(function () {
  "use strict";
  const IR = window.IR, t = IR.t;
  const form = document.getElementById("reportForm");
  if (!form) return;
  const $ = (s) => form.querySelector(s);
  const DRAFT_KEY = form.dataset.draftKey;
  const MAX_IMAGES = parseInt(form.dataset.maxImages, 10) || 4;
  const MAX_BYTES = parseInt(form.dataset.maxBytes, 10) || 8 * 1024 * 1024;
  const latIn = $("#latitude"), lngIn = $("#longitude"), srcIn = $("#location_source");
  const picker = $("[data-loc-picker]");
  const locLabel = $("[data-loc-label]"), locHint = $("[data-loc-hint]"), locCoords = $("[data-loc-coords]");
  const gpsBtn = $('[data-action="gps"]'), mapBtn = $('[data-action="pick-map"]');
  const mapEl = document.getElementById("pickMap"), mapHelp = $("[data-pick-help]");
  const fileInput = document.getElementById("images");
  const previews = $("[data-previews]");
  let files = [];

  /* ---------- location: ONLY "Use my location" (GPS) or "Pick on map" ---------- */
  function setState(state, label, hint) {
    picker.dataset.state = state;
    if (label != null) locLabel.textContent = label;
    if (hint != null) locHint.textContent = hint;
  }
  function kmText(km) { return IR.lang === "ar" ? km + " " + t("km") : t("km") + " " + km; }

  let lookupSeq = 0;
  async function applyCoords(lat, lng, source, accuracy) {
    latIn.value = lat.toFixed(6); lngIn.value = lng.toFixed(6); srcIn.value = source;
    locCoords.textContent = latIn.value + ", " + lngIn.value + (accuracy ? "  (± " + Math.round(accuracy) + " m)" : "");
    const err = form.querySelector('[data-err="latitude"]'); if (err) err.textContent = "";
    setState("ok", t(source === "gps" ? "locationFromGps" : "locationFromMap"), t("locating"));
    if (pickMarker) pickMarker.setLatLng([lat, lng]);
    const seq = ++lookupSeq;
    const r = await IR.api(IR.endpoints.locate + "?" + new URLSearchParams({ lat: latIn.value, lng: lngIn.value })).catch(() => null);
    if (seq !== lookupSeq) return; // a newer point was chosen meanwhile
    const d = r && r.data && r.data.data;
    if (d && d.on_road) {
      setState("ok", kmText(d.km) + (d.section ? " — " + d.section.name : ""), t("autoDetected"));
    } else if (d) {
      setState("warn", t(source === "gps" ? "locationFromGps" : "locationFromMap"), t("locationOffRoadKept"));
    } else {
      setState("ok", null, t("locationSavedOffline")); // offline: coordinates kept, the server calculates the km
    }
    saveDraft();
  }

  function geoErrorMessage(e) {
    if (!e) return t("locationUnavailable");
    if (e.code === "insecure") return t("locationInsecure");
    if (e.code === "unsupported") return t("locationUnsupported");
    if (e.code === 1) return t("locationDenied");
    if (e.code === 3) return t("locationTimeout");
    return t("locationUnavailable");
  }

  gpsBtn.addEventListener("click", async () => {
    gpsBtn.disabled = true;
    const prev = picker.dataset.state;
    setState("busy", t("locating"), t("locatingHint"));
    try {
      const pos = await IR.geolocate();
      await applyCoords(pos.coords.latitude, pos.coords.longitude, "gps", pos.coords.accuracy);
      if (pickMap) pickMap.setView([pos.coords.latitude, pos.coords.longitude], 15);
    } catch (e) {
      setState(prev === "ok" ? "ok" : "error", prev === "ok" ? null : t("locationNotSet"), geoErrorMessage(e) + " " + t("orPickOnMap"));
    } finally {
      gpsBtn.disabled = false;
    }
  });

  let pickMap = null, pickMarker = null;
  function placeMarker(latlng) {
    if (pickMarker) { pickMarker.setLatLng(latlng); return; }
    pickMarker = L.marker(latlng, { draggable: true, autoPan: true, keyboard: true, title: t("dragMarker") }).addTo(pickMap);
    pickMarker.on("dragend", () => { const p = pickMarker.getLatLng(); applyCoords(p.lat, p.lng, "map"); });
  }
  mapBtn.addEventListener("click", async () => {
    const open = mapEl.classList.contains("d-none");
    mapEl.classList.toggle("d-none", !open); mapHelp.classList.toggle("d-none", !open);
    mapBtn.setAttribute("aria-pressed", open ? "true" : "false");
    if (!open) return;
    if (!window.L) { mapEl.textContent = t("mapUnavailable"); return; }
    if (pickMap) { setTimeout(() => pickMap.invalidateSize(), 50); return; }
    const r = await IR.api(IR.endpoints.road).catch(() => null);
    const road = r && r.data && r.data.data;
    const m = road ? road.map : { lat: 31.2, lng: 16.6, zoom: 8, tiles: picker.dataset.tiles || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "&copy; OpenStreetMap" };
    pickMap = L.map(mapEl, { tap: true }).setView([m.lat, m.lng], m.zoom);
    L.tileLayer(m.tiles, { maxZoom: 19, attribution: m.attribution }).addTo(pickMap);
    if (road && road.polyline.length > 1) L.polyline(road.polyline.map((p) => [p[0], p[1]]), { color: "#0e6e76", weight: 5, opacity: 0.7 }).addTo(pickMap);
    if (latIn.value && lngIn.value) { placeMarker([+latIn.value, +lngIn.value]); pickMap.setView([+latIn.value, +lngIn.value], 15); }
    pickMap.on("click", (e) => { placeMarker(e.latlng); applyCoords(e.latlng.lat, e.latlng.lng, "map"); });
    setTimeout(() => pickMap.invalidateSize(), 50);
    mapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  /* ---------- title suggestion from category ---------- */
  form.querySelectorAll('input[name="category_id"]').forEach((r) => r.addEventListener("change", () => {
    const title = $("#title");
    if (!title.value || title.dataset.auto === "1") { title.value = r.dataset.name; title.dataset.auto = "1"; }
    saveDraft();
  }));
  $("#title").addEventListener("input", (e) => { e.target.dataset.auto = "0"; });

  /* ---------- images ---------- */
  function renderPreviews() {
    previews.textContent = "";
    files.forEach((f, i) => {
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.alt = f.name; img.src = URL.createObjectURL(f);
      img.onload = () => URL.revokeObjectURL(img.src);
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("aria-label", t("removeImage")); b.innerHTML = '<i class="bi bi-x"></i>';
      b.addEventListener("click", () => { files.splice(i, 1); renderPreviews(); });
      fig.append(img, b); previews.appendChild(fig);
    });
  }
  fileInput.addEventListener("change", () => {
    const err = form.querySelector('[data-err="images"]');
    err.textContent = "";
    for (const f of fileInput.files) {
      if (files.length >= MAX_IMAGES) { err.textContent = t("tooManyImages"); break; }
      if (f.size > MAX_BYTES) { err.textContent = f.name + " > " + Math.round(MAX_BYTES / 1048576) + " MB"; continue; }
      files.push(f);
    }
    fileInput.value = "";
    renderPreviews();
  });

  /* ---------- drafts (text fields only; never marked as sent) ---------- */
  const DRAFT_FIELDS = ["title", "latitude", "longitude", "location_source", "description", "guest_name", "guest_phone"];
  function collect() {
    const d = { at: Date.now() };
    DRAFT_FIELDS.forEach((n) => { const el = form.elements[n]; if (el) d[n] = el.value; });
    const c = form.querySelector('input[name="category_id"]:checked'); d.category_id = c ? c.value : "";
    const s = form.querySelector('input[name="severity"]:checked'); d.severity = s ? s.value : "";
    return d;
  }
  let draftTimer;
  function saveDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => {
      const d = collect();
      if (d.description || d.latitude || d.category_id) IR.store.set(DRAFT_KEY, d);
    }, 400);
  }
  form.addEventListener("input", saveDraft);
  function restoreDraft() {
    const hasServerValues = form.querySelector(".is-invalid") || latIn.value;
    const d = IR.store.get(DRAFT_KEY);
    if (!d || hasServerValues || Date.now() - d.at > 7 * 24 * 3600 * 1000) return;
    DRAFT_FIELDS.forEach((n) => { const el = form.elements[n]; if (el && d[n] != null) el.value = d[n]; });
    if (d.category_id) { const c = form.querySelector('input[name="category_id"][value="' + CSS.escape(d.category_id) + '"]'); if (c) c.checked = true; }
    if (d.severity) { const s = form.querySelector('input[name="severity"][value="' + CSS.escape(d.severity) + '"]'); if (s) s.checked = true; }
    $("[data-draft-note]").textContent = t("draftRestored");
    if (latIn.value && lngIn.value) applyCoords(+latIn.value, +lngIn.value, srcIn.value || "map");
  }
  restoreDraft();

  /* ---------- submit via fetch; success only after the server confirms ---------- */
  const errBox = $("[data-form-error]");
  const submitBtn = $("[data-submit]");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errBox.classList.add("d-none");
    form.querySelectorAll("[data-err]").forEach((x) => (x.textContent = ""));
    if (!latIn.value || !lngIn.value) {
      setState("error", t("locationNotSet"), t("locationRequired"));
      picker.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!navigator.onLine) {
      IR.store.set(DRAFT_KEY, collect());
      errBox.textContent = t("offlineSubmit"); errBox.classList.remove("d-none");
      errBox.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    // Page may have been restored from the offline cache → refresh the CSRF token first
    try {
      const tk = await IR.api("/api/v1/csrf");
      if (tk.ok && tk.data && tk.data.data) {
        const m = document.querySelector('meta[name="csrf-token"]'); if (m) m.content = tk.data.data.token;
        const hidden = form.querySelector('input[name="csrf_token"]'); if (hidden) hidden.value = tk.data.data.token;
      }
    } catch (e2) { /* handled by the POST below */ }
    const fd = new FormData(form);
    fd.delete("images");
    files.forEach((f) => fd.append("images", f, f.name));
    const label = submitBtn.querySelector("span"); const orig = label.textContent;
    submitBtn.disabled = true; label.textContent = t("sending");
    try {
      const res = await fetch(form.action || location.href, {
        method: "POST", body: fd, credentials: "same-origin",
        headers: { "X-Requested-With": "fetch", Accept: "application/json", "X-CSRFToken": IR.csrf() },
      });
      const data = await res.json().catch(() => null);
      if (res.status === 201 && data && data.ok) {
        IR.store.del(DRAFT_KEY);
        location.assign(data.redirect);
        return;
      }
      if (data && data.error && data.error.fields) {
        Object.entries(data.error.fields).forEach(([k, v]) => {
          const el = form.querySelector('[data-err="' + k + '"]');
          if (el) el.textContent = v.join(" ");
        });
        const first = form.querySelector("[data-err]:not(:empty)");
        if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
      } else {
        errBox.textContent = (data && data.error && data.error.message) || t("networkError");
        errBox.classList.remove("d-none");
      }
    } catch (err) {
      IR.store.set(DRAFT_KEY, collect());
      errBox.textContent = t("offlineSubmit"); errBox.classList.remove("d-none");
    } finally {
      submitBtn.disabled = false; label.textContent = orig;
    }
  });
})();
