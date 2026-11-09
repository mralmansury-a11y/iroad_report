/* Admin helpers (v1.1): off-canvas sidebar, responsive stacked tables, filter toggles, report mini-map. */
(function () {
  "use strict";
  const side = document.getElementById("adSide");
  const backdrop = document.querySelector(".ad-backdrop");
  const toggles = document.querySelectorAll("[data-toggle-side]");
  const mqDesktop = window.matchMedia("(min-width: 992px)");

  function setSide(open) {
    if (!side) return;
    side.classList.toggle("open", open);
    if (backdrop) backdrop.classList.toggle("show", open);
    document.body.classList.toggle("ad-lock", open && !mqDesktop.matches);
    toggles.forEach((b) => b.setAttribute("aria-expanded", open ? "true" : "false"));
    if (open) side.focus({ preventScroll: true });
  }
  toggles.forEach((b) => b.addEventListener("click", () => setSide(!side.classList.contains("open"))));
  document.querySelectorAll("[data-close-side]").forEach((el) => el.addEventListener("click", () => setSide(false)));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && side && side.classList.contains("open")) setSide(false); });
  if (side) side.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", () => { if (!mqDesktop.matches) setSide(false); }));
  mqDesktop.addEventListener("change", (e) => { if (e.matches) setSide(false); });

  // Swipe to close (touch devices)
  if (side) {
    let x0 = null;
    side.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    side.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      const rtl = document.documentElement.dir === "rtl";
      if ((rtl && dx > 60) || (!rtl && dx < -60)) setSide(false);
      x0 = null;
    });
  }

  // Tables → stacked cards on phones: copy each column header into data-label
  document.querySelectorAll(".ad-content table.table").forEach((table) => {
    if (table.classList.contains("no-stack")) return;
    const heads = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent.trim());
    if (!heads.length) return;
    table.classList.add("ad-stack");
    table.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).forEach((td, i) => {
        if (!td.hasAttribute("data-label")) td.setAttribute("data-label", td.hasAttribute("colspan") ? "" : (heads[i] || ""));
      });
    });
  });

  // Collapsible filter panels on phones
  document.querySelectorAll("[data-filters-toggle]").forEach((btn) => {
    const body = document.getElementById(btn.getAttribute("aria-controls"));
    if (!body) return;
    if (body.dataset.active === "1") { body.classList.add("show"); btn.setAttribute("aria-expanded", "true"); }
    btn.addEventListener("click", () => {
      const open = !body.classList.contains("show");
      body.classList.toggle("show", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  // Report location mini-map
  const mapEl = document.getElementById("reportMap");
  if (mapEl && window.L) {
    const lat = parseFloat(mapEl.dataset.lat), lng = parseFloat(mapEl.dataset.lng);
    const map = L.map(mapEl, { scrollWheelZoom: false }).setView([lat, lng], 13);
    L.tileLayer(mapEl.dataset.tiles || "https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap" }).addTo(map);
    L.marker([lat, lng]).addTo(map);
    window.addEventListener("resize", () => map.invalidateSize());
  }
})();
