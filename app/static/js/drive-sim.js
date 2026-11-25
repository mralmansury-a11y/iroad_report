/* DEVELOPMENT ONLY — simulated GPS for driving mode (/drive?simulate=1).
 * Loaded only when the server runs with DRIVE_SIMULATOR=True (DevelopmentConfig); never in production.
 * Drives in a straight line towards the nearest eligible report: starts 7 km before it and continues 2 km
 * past it, so both alert stages and the "passed" logic can be checked by hand.
 * Query options: ?simulate=1&lat=..&lng=..&speed=<m/s>&acc=<accuracy m>
 */
(function () {
  "use strict";
  const START_BEFORE_M = 7000, PAST_M = 2000, TICK_MS = 1000;

  function create(cfg, deps) {
    const G = deps.geo, sim = cfg.sim || {};
    let timer = null, stopped = false;
    const halt = () => { stopped = true; clearInterval(timer); timer = null; };

    async function plan() {
      const origin = { lat: sim.lat, lng: sim.lng };
      try {
        const r = await window.IR.api(cfg.endpoint, { method: "POST", json: { lat: origin.lat, lng: origin.lng, radius_km: 50 } });
        const items = (r.ok && r.data && r.data.data && r.data.data.items) || [];
        if (items.length) {
          const target = items[0];
          const back = G.distanceM(target, origin) > 50 ? G.bearingDeg(target, origin) : 270;
          const start = G.destination(target, back, START_BEFORE_M);
          return { start, bearing: G.bearingDeg(start, target), length: START_BEFORE_M + PAST_M };
        }
      } catch (e) { /* fall through */ }
      deps.notice((cfg.i18n || {}).simNoReports);
      return { start: origin, bearing: 90, length: 20000 };
    }

    return {
      async start(onFix) {
        const p = await plan();
        if (stopped) return; // the trip ended while the route was being planned
        const speed = sim.speed_mps > 0 ? sim.speed_mps : 30;
        let travelled = 0;
        const emit = () => {
          const pos = G.destination(p.start, p.bearing, travelled);
          onFix({ lat: pos.lat, lng: pos.lng, accuracy: sim.accuracy_m, heading: p.bearing, speed, timestamp: Date.now() });
          travelled += speed * (TICK_MS / 1000);
          if (travelled > p.length) halt();
        };
        emit();
        timer = setInterval(emit, TICK_MS);
      },
      stop: halt,
    };
  }

  window.IRDriveSim = { create };
})();
