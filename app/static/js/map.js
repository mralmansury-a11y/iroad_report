/* Public road map (Leaflet + OpenStreetMap). Works in RTL and LTR.
 * Offline: the page, the road line and the report list come from the service-worker caches, viewed tiles
 * from the tile cache (crossOrigin → cacheable CORS tiles). The user's position comes from the device GPS
 * and is followed live, with or without internet; it never leaves the device. */
(function () {
  "use strict";
  const IR = window.IR;
  const el = document.getElementById("roadMap");
  if (!el || !window.L) return;
  const COLORS = { high: "#c0392b", medium: "#e2a73e", low: "#6fb5a8" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  (async function () {
    const [roadR, repR] = await Promise.all([IR.api(IR.endpoints.road), IR.api(IR.endpoints.mapReports)]).catch(() => [null, null]);
    const road = roadR && roadR.data && roadR.data.data;
    const m = road ? road.map : { lat: 31.2, lng: 16.6, zoom: 7, tiles: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "© OpenStreetMap" };
    const map = L.map(el, { zoomControl: true }).setView([m.lat, m.lng], m.zoom);
    L.tileLayer(m.tiles, { maxZoom: 18, attribution: m.attribution, crossOrigin: true }).addTo(map);
    const bounds = [];
    if (road && road.polyline.length > 1) {
      const pts = road.polyline.map((p) => [p[0], p[1]]);
      L.polyline(pts, { color: "#0e6e76", weight: 6, opacity: 0.75 }).addTo(map);
      bounds.push(...pts);
    }
    const items = (repR && repR.data && repR.data.data && repR.data.data.items) || [];
    items.forEach((r) => {
      L.circleMarker([r.lat, r.lng], { radius: 8, color: "#fff", weight: 2, fillColor: COLORS[r.severity.code] || "#999", fillOpacity: 0.95 })
        .bindPopup('<strong>' + esc(r.title) + '</strong><br><span class="num">' + esc(r.km_label) + '</span> · ' + esc(r.status.name) +
          '<br><small>' + esc(r.created_rel) + '</small><br><a href="' + esc(r.url) + '">' + esc(r.reference) + "</a>")
        .addTo(map);
      bounds.push([r.lat, r.lng]);
    });
    if (bounds.length > 1) map.fitBounds(bounds, { padding: [24, 24] });
    if ("geolocation" in navigator) {
      navigator.permissions && navigator.permissions.query({ name: "geolocation" }).then((p) => {
        if (p.state !== "granted") return;
        let me = null;
        navigator.geolocation.watchPosition((pos) => {
          const ll = [pos.coords.latitude, pos.coords.longitude];
          if (me) { me.setLatLng(ll); return; }
          me = L.circleMarker(ll, { radius: 7, color: "#fff", weight: 3, fillColor: "#34668e", fillOpacity: 1 })
            .bindTooltip(IR.t("youAreHere")).addTo(map);
        }, () => {}, { enableHighAccuracy: true, maximumAge: 10000 });
      }).catch(() => {});
    }
  })();
})();
