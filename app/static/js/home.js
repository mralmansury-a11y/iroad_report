/* Home: location card (Figma «موقعك التقريبي على الطريق»), statistics from the backend. */
(function () {
  "use strict";
  const IR = window.IR, t = IR.t;
  const card = document.getElementById("locCard");
  if (!card) return;
  const bind = (k) => card.querySelector('[data-bind="' + k + '"]');
  const svg = card.querySelector("svg.ir-road");
  const path = svg.querySelector(".road-body");
  const LOC_KEY = "ir-last-location";
  const ROAD_STATUS_CLASS = { open: "ir-pill-open", partial: "ir-pill-partial", closed: "ir-pill-closed" };

  function pointAt(frac) {
    const len = path.getTotalLength();
    return path.getPointAtLength(Math.max(0, Math.min(1, frac)) * len);
  }

  function render(d) {
    bind("km_label").textContent = d.km_label || "—";
    bind("section").textContent = d.section ? "· " + d.section : "";
    const pill = bind("road_status");
    pill.className = "ir-pill " + (ROAD_STATUS_CLASS[d.road_status] || "ir-pill-unknown");
    pill.querySelector("span").textContent = d.road_status ? d.road_status_label : "—";
    bind("nearby_count").textContent = d.nearby_count == null ? "—" : String(d.nearby_count);
    bind("visibility").textContent = d.visibility_pct == null ? "—" : d.visibility_pct + "%";
    bind("avg_response").textContent = d.avg_response_label || "—";
    const hint = bind("hint");
    if (hint) hint.textContent = d.km == null ? "" : (d.source === "gps" ? t("autoDetected") : "");

    // markers: x position relative to user km (±radius). RTL: increasing km goes to the left.
    const g = svg.querySelector("[data-markers]");
    g.textContent = "";
    const you = svg.querySelector("[data-you]");
    card.classList.toggle("has-loc", d.km != null);
    if (d.km == null) { you.style.display = "none"; return; }
    const r = d.radius_km || 20;
    const rtl = document.documentElement.dir === "rtl";
    const frac = (km) => { let f = 0.5 + (km - d.km) / (2 * r) * 0.9; return rtl ? 1 - f : f; };
    (d.markers || []).forEach((m) => {
      const p = pointAt(frac(m.km));
      const c = document.createElementNS("http://www.w3.org/2000/svg", "ellipse");
      c.setAttribute("cx", p.x); c.setAttribute("cy", p.y); c.setAttribute("rx", 7); c.setAttribute("ry", 5);
      c.setAttribute("class", "mk-" + m.severity);
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = m.title; c.appendChild(title);
      g.appendChild(c);
    });
    const pc = pointAt(0.5); // the user is always centred on the strip
    you.setAttribute("transform", "translate(" + pc.x + "," + pc.y + ")");
    you.style.display = "";
  }

  async function load(params) {
    const qs = new URLSearchParams(params).toString();
    card.setAttribute("aria-busy", "true");
    const r = await IR.api(IR.endpoints.home + (qs ? "?" + qs : "")).catch(() => null);
    card.removeAttribute("aria-busy");
    if (r && r.ok && r.data && r.data.data) render(r.data.data);
  }

  function useGps(silent) {
    if (!silent) bind("hint").textContent = t("locating");
    IR.geolocate().then(async (pos) => {
      const p = { lat: pos.coords.latitude.toFixed(6), lng: pos.coords.longitude.toFixed(6) };
      const r = await IR.api(IR.endpoints.locate + "?" + new URLSearchParams(p)).catch(() => null);
      const d = r && r.data && r.data.data;
      if (d && d.on_road) {
        IR.store.set(LOC_KEY, { km: d.km, src: "gps", at: Date.now() });
        load({ km: d.km });
      } else {
        bind("hint").textContent = t("locationOffRoad");
        load({});
      }
    }).catch((err) => {
      const msg = err && err.code === "insecure" ? t("locationInsecure") : (err && err.code === 1 ? t("locationDenied")
        : (err && err.code === 3 ? t("locationTimeout") : t("locationUnavailable")));
      bind("hint").textContent = msg;
      if (!silent) IR.toast(msg);
      load({});
    });
  }

  card.querySelector('[data-action="locate"]').addEventListener("click", () => useGps(false));
  card.querySelector('[data-action="section"]').addEventListener("change", (e) => {
    const opt = e.target.selectedOptions[0];
    if (!opt || !opt.value) return;
    const km = parseFloat(opt.dataset.km);
    IR.store.set(LOC_KEY, { km, section: opt.value, src: "manual", at: Date.now() });
    load({ km, section: opt.value });
  });

  // Initial state: last known location (≤ 6 h) → else ask silently if permission already granted → else stats without location
  const last = IR.store.get(LOC_KEY);
  if (last && Date.now() - last.at < 6 * 3600 * 1000) load({ km: last.km });
  else if (navigator.permissions && navigator.permissions.query) {
    navigator.permissions.query({ name: "geolocation" }).then((p) => (p.state === "granted" ? useGps(true) : load({}))).catch(() => load({}));
  } else load({});
})();
