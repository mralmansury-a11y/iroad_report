/* Analytics charts (Chart.js) with bilingual labels supplied by the server. */
(function () {
  "use strict";
  const el = document.getElementById("chartData");
  if (!el || !window.Chart) return;
  const d = JSON.parse(el.textContent);
  const css = getComputedStyle(document.documentElement);
  const text = css.getPropertyValue("--ir-text").trim() || "#ddd";
  const grid = css.getPropertyValue("--ir-border").trim() || "#444";
  const rtl = document.documentElement.dir === "rtl";
  Chart.defaults.color = text;
  Chart.defaults.font.family = "Tajawal, system-ui, sans-serif";
  Chart.defaults.borderColor = grid;
  const legend = { rtl, position: "bottom", labels: { usePointStyle: true } };
  const tooltip = { rtl, textDirection: rtl ? "rtl" : "ltr" };
  const PALETTE = ["#c0392b", "#e2a73e", "#2f5f86", "#5a4a99", "#0e6e76", "#8a867e"];

  new Chart(document.getElementById("chTime"), {
    type: "line",
    data: { labels: d.months, datasets: [
      { label: window.IR.t("reports"), data: d.created, borderColor: "#34668e", backgroundColor: "rgba(52,102,142,.2)", tension: 0.3, fill: true },
      { label: window.IR.t("resolved"), data: d.resolved, borderColor: "#0e6e76", backgroundColor: "rgba(14,110,118,.15)", tension: 0.3, fill: true },
    ] },
    options: { maintainAspectRatio: false, plugins: { legend, tooltip }, scales: { x: { reverse: rtl }, y: { beginAtZero: true, ticks: { precision: 0 } } } },
  });
  new Chart(document.getElementById("chStatus"), {
    type: "doughnut",
    data: { labels: d.statusLabels, datasets: [{ data: d.statusValues, backgroundColor: PALETTE, borderWidth: 0 }] },
    options: { maintainAspectRatio: false, plugins: { legend, tooltip } },
  });
  const bar = (id, labels, values, color) => new Chart(document.getElementById(id), {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: color, borderRadius: 6 }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip },
      scales: { x: { beginAtZero: true, reverse: rtl, ticks: { precision: 0 } }, y: { position: rtl ? "right" : "left" } } },
  });
  bar("chCat", d.catLabels, d.catValues, "#34668e");
  bar("chSec", d.secLabels, d.secValues, "#0e6e76");
})();
