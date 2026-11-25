/* Driving-mode decision engine — PURE state machine (no DOM, no timers, no network).
 * Input: GPS fixes + the list of verified hazards. Output: what to show and which alerts to fire.
 * Kept free of browser APIs so it runs unchanged in Node tests and in a future native (Capacitor) wrapper.
 *
 *   const engine = IRDriveEngine.createEngine({ farM: 5000, nearM: 500, coneDeg: 40, bbox });
 *   engine.setHazards(items);                 // [{reference, lat, lng, ...}]
 *   const s = engine.update(fix);             // fix: {lat, lng, accuracy, heading, speed}
 *   s.status   → "ok" | "no_heading" | "weak_gps" | "outside" | "invalid"
 *   s.upcoming → hazards ahead, nearest first: [{hazard, id, distanceM, bearing, stage}]
 *   s.alerts   → alerts to fire NOW (each (hazard × stage) at most once per trip), near stage first
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory(require("./geo.js"));
  else root.IRDriveEngine = factory(root.IRGeo);
})(typeof self !== "undefined" ? self : this, function (G) {
  "use strict";

  const DEFAULTS = Object.freeze({
    farM: 5000,              // first alert
    nearM: 500,              // second alert
    coneDeg: 40,             // ± half-angle of the forward cone
    alwaysAheadM: 150,       // closer than this a hazard ALREADY SEEN AHEAD stays ahead whatever the angle
    maxAccuracyM: 100,       // worse GPS accuracy pauses alerts
    minMoveM: 30,            // minimum movement before a heading is computed from two fixes (jitter filter)
    minGpsHeadingSpeed: 2,   // m/s: below this the device heading is unreliable
    passedAngleDeg: 90,      // a hazard more than this off the heading is behind the driver
    listSize: 5,
    bbox: null,              // {min_lat, max_lat, min_lng, max_lng}: alerts only inside (Libya)
    // reference when present, else the id, else the position (never one shared "undefined" key)
    keyOf: (h) => (h.reference != null ? String(h.reference) : h.id != null ? String(h.id) : "@" + h.lat + "," + h.lng),
  });

  /** Alert stage for a distance: "near" ≤ nearM < "far" ≤ farM, otherwise null. */
  function stageFor(distanceM, farM, nearM) {
    if (!(distanceM >= 0)) return null;
    if (distanceM <= nearM) return "near";
    if (distanceM <= farM) return "far";
    return null;
  }

  /**
   * Driving direction: the GPS heading when moving fast enough, otherwise the bearing between the
   * last anchor and the current fix once they are at least `minMoveM` apart (ignores GPS jitter).
   */
  function createHeadingTracker(opts) {
    const minMoveM = opts && opts.minMoveM != null ? opts.minMoveM : DEFAULTS.minMoveM;
    const minSpeed = opts && opts.minGpsHeadingSpeed != null ? opts.minGpsHeadingSpeed : DEFAULTS.minGpsHeadingSpeed;
    let anchor = null, heading = null;
    return {
      update(fix) {
        const p = { lat: fix.lat, lng: fix.lng };
        if (Number.isFinite(fix.heading) && Number.isFinite(fix.speed) && fix.speed > minSpeed) {
          heading = G.normalizeDeg(fix.heading);
          anchor = p;
        } else if (!anchor) {
          anchor = p;
        } else if (G.distanceM(anchor, p) >= minMoveM) {
          heading = G.bearingDeg(anchor, p);
          anchor = p;
        }
        return heading;
      },
      get heading() { return heading; },
      reset() { anchor = null; heading = null; },
    };
  }

  /** Remembers fired (hazard × stage) pairs. A near alert also consumes the far one (never far after near). */
  function createAlertLog() {
    const fired = new Set();
    return {
      take(id, stage) {
        const k = id + "|" + stage;
        if (fired.has(k)) return false;
        fired.add(k);
        if (stage === "near") fired.add(id + "|far");
        return true;
      },
      has(id, stage) { return fired.has(id + "|" + stage); },
      clear() { fired.clear(); },
    };
  }

  /** Should the hazard list be fetched again? (first time, every refreshMs, or after refreshDistM driven) */
  function shouldRefresh(last, now, pos, refreshMs, refreshDistM) {
    if (!last || last.at == null) return true;
    if (now - last.at >= refreshMs) return true;
    return !!(last.pos && pos && G.distanceM(last.pos, pos) >= refreshDistM);
  }

  /** Rounded distance for display/speech: {value, unit}. 10 m steps below 1 km, then 0.1 km (1 km steps ≥ 10 km). */
  function roundDistance(m) {
    if (!(m >= 0)) return { value: 0, unit: "m" };
    if (m < 995) return { value: Math.max(10, Math.round(m / 10) * 10), unit: "m" };
    const km = m / 1000;
    return { value: km >= 9.95 ? Math.round(km) : Math.round(km * 10) / 10, unit: "km" };
  }

  function createEngine(options) {
    const o = Object.assign({}, DEFAULTS, options || {});
    if (!(o.nearM < o.farM)) throw new Error("nearM must be smaller than farM");
    const heading = createHeadingTracker(o);
    const log = createAlertLog();
    const passed = new Set();
    const seenAhead = new Set();
    let hazards = [];
    let last = { status: "invalid", position: null, heading: null, accuracy: null, upcoming: [], alerts: [] };

    function result(status, extra) {
      last = Object.assign({ status, position: last.position, heading: heading.heading, accuracy: last.accuracy,
                             upcoming: last.upcoming, alerts: [] }, extra || {});
      return last;
    }

    return {
      options: o,
      /** Replace the hazard list (e.g. after a refresh). Alert history and passed hazards are kept. */
      setHazards(list) {
        hazards = (list || []).filter((h) => G.validPoint(h)).map((h) => ({ id: o.keyOf(h), hazard: h }));
      },
      get hazardCount() { return hazards.length; },
      isPassed(id) { return passed.has(id); },

      update(fix) {
        const pos = fix && { lat: fix.lat, lng: fix.lng };
        if (!G.validPoint(pos)) return result("invalid");
        const accuracy = Number.isFinite(fix.accuracy) ? fix.accuracy : null;
        if (accuracy != null && accuracy > o.maxAccuracyM) {
          return result("weak_gps", { accuracy }); // keep the last trusted position, heading and list
        }
        const hd = heading.update(fix);
        if (o.bbox && !G.inBox(pos, o.bbox)) {
          return result("outside", { position: pos, accuracy, heading: hd, upcoming: [] });
        }

        const rows = [];
        for (const { id, hazard } of hazards) {
          if (passed.has(id)) continue;
          const distanceM = G.distanceM(pos, hazard);
          const bearing = G.bearingDeg(pos, hazard);
          if (hd == null) {
            rows.push({ hazard, id, distanceM, bearing, stage: stageFor(distanceM, o.farM, o.nearM), ahead: null });
            continue;
          }
          // the short-range override only keeps a hazard ahead; it never turns one behind into "ahead"
          const ahead = G.isAhead(hd, bearing, distanceM, o.coneDeg, seenAhead.has(id) ? o.alwaysAheadM : 0);
          if (ahead) {
            seenAhead.add(id);
            rows.push({ hazard, id, distanceM, bearing, stage: stageFor(distanceM, o.farM, o.nearM), ahead: true });
          } else if (seenAhead.has(id) && distanceM <= o.nearM && G.angleDiff(hd, bearing) > o.passedAngleDeg) {
            passed.add(id); // went past it: drop it for the rest of the trip
          }
        }
        rows.sort((a, b) => a.distanceM - b.distanceM);
        const upcoming = rows.slice(0, o.listSize);

        if (hd == null) return result("no_heading", { position: pos, accuracy, heading: null, upcoming });

        const alerts = [];
        for (const r of rows) {
          if (r.stage && log.take(r.id, r.stage)) alerts.push({ hazard: r.hazard, id: r.id, stage: r.stage, distanceM: r.distanceM });
        }
        alerts.sort((a, b) => (a.stage === b.stage ? a.distanceM - b.distanceM : a.stage === "near" ? -1 : 1));
        return result("ok", { position: pos, accuracy, heading: hd, upcoming, alerts });
      },

      /** Forget everything (new trip). */
      reset() {
        heading.reset(); log.clear(); passed.clear(); seenAhead.clear(); hazards = [];
        last = { status: "invalid", position: null, heading: null, accuracy: null, upcoming: [], alerts: [] };
      },
    };
  }

  return { DEFAULTS, stageFor, createHeadingTracker, createAlertLog, shouldRefresh, roundDistance, createEngine };
});
