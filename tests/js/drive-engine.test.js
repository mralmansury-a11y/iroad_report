/* Driving-mode decision engine — run with: node --test tests/js/ */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const G = require("../../app/static/js/geo.js");
const E = require("../../app/static/js/drive-engine.js");

const LIBYA = { min_lat: 19.5, max_lat: 33.5, min_lng: 9.3, max_lng: 25.2 };
const ORIGIN = { lat: 27.0377, lng: 14.4283 }; // Sabha

function hazard(ref, from, bearing, distM, extra) {
  const p = G.destination(from, bearing, distM);
  return Object.assign({ reference: ref, lat: p.lat, lng: p.lng, severity: { code: "high" }, category: { name: "x" } }, extra || {});
}

/** Simulated straight drive: returns every engine state, one fix every `stepM` metres. */
function drive(engine, start, bearing, totalM, stepM, fixExtra) {
  const states = [];
  for (let d = 0; d <= totalM; d += stepM) {
    const p = G.destination(start, bearing, d);
    states.push(Object.assign({ travelled: d }, engine.update(Object.assign({ lat: p.lat, lng: p.lng, accuracy: 10, heading: bearing, speed: 25 }, fixExtra || {}))));
  }
  return states;
}

const allAlerts = (states) => states.flatMap((s) => s.alerts.map((a) => Object.assign({ travelled: s.travelled }, a)));

test("stageFor: boundaries", () => {
  assert.equal(E.stageFor(0, 5000, 500), "near");
  assert.equal(E.stageFor(500, 5000, 500), "near");
  assert.equal(E.stageFor(501, 5000, 500), "far");
  assert.equal(E.stageFor(5000, 5000, 500), "far");
  assert.equal(E.stageFor(5001, 5000, 500), null);
  assert.equal(E.stageFor(NaN, 5000, 500), null);
  assert.equal(E.stageFor(-1, 5000, 500), null);
});

test("roundDistance", () => {
  assert.deepEqual(E.roundDistance(0), { value: 10, unit: "m" });
  assert.deepEqual(E.roundDistance(444), { value: 440, unit: "m" });
  assert.deepEqual(E.roundDistance(994), { value: 990, unit: "m" });
  assert.deepEqual(E.roundDistance(995), { value: 1, unit: "km" });
  assert.deepEqual(E.roundDistance(4860), { value: 4.9, unit: "km" });
  assert.deepEqual(E.roundDistance(12400), { value: 12, unit: "km" });
  assert.deepEqual(E.roundDistance(NaN), { value: 0, unit: "m" });
});

test("alert log: once per (hazard × stage); near consumes far", () => {
  const log = E.createAlertLog();
  assert.equal(log.take("A", "far"), true);
  assert.equal(log.take("A", "far"), false);
  assert.equal(log.take("A", "near"), true);
  assert.equal(log.take("A", "near"), false);
  assert.equal(log.take("B", "near"), true);
  assert.equal(log.take("B", "far"), false, "never a far alert after the near one");
  log.clear();
  assert.equal(log.take("A", "far"), true);
});

test("heading tracker: GPS heading when moving fast", () => {
  const h = E.createHeadingTracker({});
  assert.equal(h.update({ lat: 27, lng: 14, heading: 123, speed: 20 }), 123);
  assert.equal(h.update({ lat: 27, lng: 14, heading: -10, speed: 20 }), 350, "normalised");
});

test("heading tracker: computed from two fixes ≥ 30 m apart, ignores jitter", () => {
  const h = E.createHeadingTracker({ minMoveM: 30 });
  const a = { lat: 27, lng: 14 };
  assert.equal(h.update(Object.assign({ heading: null, speed: null }, a)), null);
  const jitter = G.destination(a, 90, 12);
  assert.equal(h.update({ lat: jitter.lat, lng: jitter.lng, heading: null, speed: 0.5 }), null, "12 m is jitter");
  const moved = G.destination(a, 0, 40);
  const hd = h.update({ lat: moved.lat, lng: moved.lng, heading: 200, speed: 1 }); // slow → GPS heading ignored
  assert.ok(G.angleDiff(hd, 0) < 0.5, "north from the two fixes, got " + hd);
  const jitter2 = G.destination(moved, 180, 10);
  assert.ok(G.angleDiff(h.update({ lat: jitter2.lat, lng: jitter2.lng }), 0) < 0.5, "small backward jitter keeps heading");
  h.reset();
  assert.equal(h.heading, null);
});

test("shouldRefresh: first time, every interval, after 10 km", () => {
  const p = { lat: 27, lng: 14 };
  assert.equal(E.shouldRefresh(null, 0, p, 120000, 10000), true);
  const last = { at: 1000, pos: p };
  assert.equal(E.shouldRefresh(last, 1000 + 119999, p, 120000, 10000), false);
  assert.equal(E.shouldRefresh(last, 1000 + 120000, p, 120000, 10000), true);
  assert.equal(E.shouldRefresh(last, 2000, G.destination(p, 0, 9999), 120000, 10000), false);
  assert.equal(E.shouldRefresh(last, 2000, G.destination(p, 0, 10001), 120000, 10000), true);
});

test("createEngine: rejects near ≥ far", () => {
  assert.throws(() => E.createEngine({ farM: 500, nearM: 500 }));
});

test("ACCEPTANCE: driving towards a hazard → one alert ≤ 5 km, one ≤ 500 m, no repeats", () => {
  const engine = E.createEngine({ farM: 5000, nearM: 500, coneDeg: 40, bbox: LIBYA });
  const target = hazard("IR-1", ORIGIN, 0, 8000);
  engine.setHazards([target]);
  const states = drive(engine, ORIGIN, 0, 10000, 50);
  const alerts = allAlerts(states);
  assert.equal(alerts.length, 2, JSON.stringify(alerts.map((a) => [a.stage, a.travelled])));
  assert.equal(alerts[0].stage, "far");
  assert.ok(alerts[0].distanceM <= 5000 && alerts[0].distanceM > 4900, "far fires as soon as ≤ 5 km");
  assert.equal(alerts[1].stage, "near");
  assert.ok(alerts[1].distanceM <= 500 && alerts[1].distanceM > 400, "near fires as soon as ≤ 500 m");
  // after passing, the hazard disappears from the list and is marked passed
  const last = states[states.length - 1];
  assert.equal(last.upcoming.length, 0);
  assert.equal(engine.isPassed("IR-1"), true);
});

test("hazard behind the driver is never announced", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("BEHIND", ORIGIN, 180, 3000)]);
  const states = drive(engine, ORIGIN, 0, 6000, 50);
  assert.equal(allAlerts(states).length, 0);
  assert.ok(states.every((s) => s.upcoming.length === 0));
});

test("hazard outside the forward cone is not announced; inside the cone is", () => {
  const engine = E.createEngine({ coneDeg: 40, bbox: LIBYA });
  // 60° off the heading at 3 km stays outside ±40° while driving north for 1 km
  engine.setHazards([hazard("SIDE", ORIGIN, 60, 3000), hazard("CONE", ORIGIN, 30, 3000)]);
  const states = drive(engine, ORIGIN, 0, 1000, 50);
  const ids = allAlerts(states).map((a) => a.id);
  assert.deepEqual(ids, ["CONE"]);
  assert.ok(states.every((s) => s.upcoming.every((u) => u.id !== "SIDE")));
});

test("the cone angle is configurable", () => {
  const engine = E.createEngine({ coneDeg: 70, bbox: LIBYA });
  engine.setHazards([hazard("SIDE", ORIGIN, 60, 3000)]);
  assert.equal(allAlerts(drive(engine, ORIGIN, 0, 200, 50)).length, 1);
});

test("starting within 500 m gives only the near alert", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("CLOSE", ORIGIN, 0, 400)]);
  const alerts = allAlerts(drive(engine, ORIGIN, 0, 1000, 25));
  assert.deepEqual(alerts.map((a) => a.stage), ["near"]);
});

test("several hazards: near alerts first, list sorted and limited to 5", () => {
  const engine = E.createEngine({ bbox: LIBYA, listSize: 5 });
  const hz = [800, 300, 4000, 2500, 6000, 7000, 7500].map((d, i) => hazard("H" + i, ORIGIN, 0, d));
  engine.setHazards(hz);
  const s = engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: 0, speed: 20 });
  assert.equal(s.status, "ok");
  assert.deepEqual(s.upcoming.map((u) => u.id), ["H1", "H0", "H3", "H2", "H4"]);
  assert.deepEqual(s.alerts.map((a) => [a.id, a.stage]), [["H1", "near"], ["H0", "far"], ["H3", "far"], ["H2", "far"]]);
});

test("refreshing the list keeps alert history (no repeat after refresh)", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  const h = hazard("R", ORIGIN, 0, 4000);
  engine.setHazards([h]);
  assert.equal(engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: 0, speed: 20 }).alerts.length, 1);
  engine.setHazards([Object.assign({}, h)]); // same report re-fetched
  assert.equal(engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: 0, speed: 20 }).alerts.length, 0);
});

test("a passed hazard is not listed again after a U-turn", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("U", ORIGIN, 0, 2000)]);
  drive(engine, ORIGIN, 0, 3000, 50);
  assert.equal(engine.isPassed("U"), true);
  const back = drive(engine, G.destination(ORIGIN, 0, 3000), 180, 2000, 50);
  assert.equal(allAlerts(back).length, 0);
  assert.ok(back.every((s) => s.upcoming.length === 0));
});

test("weak GPS pauses alerts and keeps the last list", () => {
  const engine = E.createEngine({ bbox: LIBYA, maxAccuracyM: 100 });
  engine.setHazards([hazard("W", ORIGIN, 0, 4000)]);
  const p = G.destination(ORIGIN, 0, 2000);
  const weak = engine.update({ lat: p.lat, lng: p.lng, accuracy: 150, heading: 0, speed: 20 });
  assert.equal(weak.status, "weak_gps");
  assert.equal(weak.alerts.length, 0);
  const ok = engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 100, heading: 0, speed: 20 });
  assert.equal(ok.status, "ok", "accuracy equal to the limit is accepted");
  assert.equal(ok.alerts.length, 1);
  const weak2 = engine.update({ lat: p.lat, lng: p.lng, accuracy: 500, heading: 0, speed: 20 });
  assert.equal(weak2.upcoming.length, 1, "last list kept");
  assert.equal(weak2.alerts.length, 0);
});

test("outside Libya: alerts paused, list emptied", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  const tunis = { lat: 36.8065, lng: 10.1815 };
  engine.setHazards([hazard("T", tunis, 0, 1000)]);
  const s = engine.update({ lat: tunis.lat, lng: tunis.lng, accuracy: 5, heading: 0, speed: 20 });
  assert.equal(s.status, "outside");
  assert.equal(s.alerts.length, 0);
  assert.equal(s.upcoming.length, 0);
});

test("no heading yet (stationary): nearest hazards listed, no alerts", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("N1", ORIGIN, 180, 300), hazard("N2", ORIGIN, 0, 900)]);
  const s = engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: null, speed: 0 });
  assert.equal(s.status, "no_heading");
  assert.equal(s.alerts.length, 0);
  assert.deepEqual(s.upcoming.map((u) => u.id), ["N1", "N2"]);
});

test("heading computed from positions when the GPS gives none", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("C", ORIGIN, 0, 3000)]);
  const states = drive(engine, ORIGIN, 0, 200, 20, { heading: null, speed: null });
  assert.equal(states[0].status, "no_heading");
  assert.equal(states[states.length - 1].status, "ok");
  assert.equal(allAlerts(states).length, 1);
});

test("invalid fixes and invalid hazards are ignored", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([{ reference: "BAD", lat: NaN, lng: 1 }, { reference: "NOPOS" }, hazard("GOOD", ORIGIN, 0, 1000)]);
  assert.equal(engine.hazardCount, 1);
  assert.equal(engine.update({ lat: NaN, lng: 14 }).status, "invalid");
  assert.equal(engine.update(null).status, "invalid");
});

test("reset starts a new trip (alerts may fire again)", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  const h = hazard("X", ORIGIN, 0, 3000);
  engine.setHazards([h]);
  assert.equal(allAlerts(drive(engine, ORIGIN, 0, 100, 50)).length, 1);
  engine.reset();
  engine.setHazards([h]);
  assert.equal(allAlerts(drive(engine, ORIGIN, 0, 100, 50)).length, 1);
});

test("a hazard just behind the driver at trip start is not announced as ahead", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("JUST-PASSED", ORIGIN, 180, 100)]);
  const states = drive(engine, ORIGIN, 0, 1000, 20);
  assert.equal(allAlerts(states).length, 0);
  assert.ok(states.every((s) => s.upcoming.length === 0));
});

test("a hazard seen ahead stays ahead at very short range (angle is meaningless there)", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  engine.setHazards([hazard("SIDE", ORIGIN, 0, 1000)]);
  drive(engine, ORIGIN, 0, 900, 50);
  // 100 m before it the driver drifts so the bearing is well outside the cone
  const s = engine.update(Object.assign(G.destination(ORIGIN, 0, 950), { accuracy: 5, heading: 90, speed: 25 }));
  assert.equal(s.upcoming.length, 1);
});

test("hazards without reference or id get distinct keys (each one is announced)", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  const a = hazard(null, ORIGIN, 0, 300), b = hazard(null, ORIGIN, 5, 400);
  const s = engine.update((engine.setHazards([a, b]), { lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: 0, speed: 20 }));
  assert.equal(s.alerts.length, 2);
  assert.notEqual(s.alerts[0].id, s.alerts[1].id);
});

test("uses the id when there is no reference", () => {
  const engine = E.createEngine({ bbox: LIBYA });
  const h = hazard(undefined, ORIGIN, 0, 1000);
  delete h.reference; h.id = 42;
  engine.setHazards([h]);
  assert.equal(engine.update({ lat: ORIGIN.lat, lng: ORIGIN.lng, accuracy: 5, heading: 0, speed: 20 }).alerts[0].id, "42");
});
