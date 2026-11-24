/* Pure geodesy helpers — run with: node --test tests/js/ */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const G = require("../../app/static/js/geo.js");

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ""} expected ${b} ±${tol}, got ${a}`);
const TRIPOLI = { lat: 32.8872, lng: 13.1913 };
const BENGHAZI = { lat: 32.1167, lng: 20.0667 };

test("distanceM: zero, symmetric, known city pair", () => {
  assert.equal(G.distanceM(TRIPOLI, TRIPOLI), 0);
  near(G.distanceM(TRIPOLI, BENGHAZI), G.distanceM(BENGHAZI, TRIPOLI), 1e-6);
  near(G.distanceM(TRIPOLI, BENGHAZI) / 1000, 648, 5, "Tripoli–Benghazi great circle");
});

test("distanceM: one degree of latitude ≈ 111.195 km", () => {
  near(G.distanceM({ lat: 0, lng: 0 }, { lat: 1, lng: 0 }), 111195, 1);
});

test("distanceM: antipodes do not produce NaN", () => {
  near(G.distanceM({ lat: 0, lng: 0 }, { lat: 0, lng: 180 }), Math.PI * G.EARTH_RADIUS_M, 1);
});

test("bearingDeg: cardinal directions", () => {
  const o = { lat: 27, lng: 14 };
  near(G.bearingDeg(o, { lat: 28, lng: 14 }), 0, 1e-9, "north");
  near(G.bearingDeg(o, { lat: 26, lng: 14 }), 180, 1e-9, "south");
  near(G.bearingDeg(o, { lat: 27, lng: 15 }), 90, 0.3, "east");
  near(G.bearingDeg(o, { lat: 27, lng: 13 }), 270, 0.3, "west");
});

test("bearingDeg: always within [0, 360)", () => {
  for (let i = 0; i < 360; i += 7) {
    const b = G.bearingDeg({ lat: 30, lng: 15 }, G.destination({ lat: 30, lng: 15 }, i, 5000));
    assert.ok(b >= 0 && b < 360);
    near(G.angleDiff(b, i), 0, 0.01, "bearing to destination");
  }
});

test("normalizeDeg", () => {
  assert.equal(G.normalizeDeg(0), 0);
  assert.equal(G.normalizeDeg(360), 0);
  assert.equal(G.normalizeDeg(-10), 350);
  assert.equal(G.normalizeDeg(725), 5);
});

test("angleDiff: across the 0°/360° wrap", () => {
  assert.equal(G.angleDiff(350, 10), 20);
  assert.equal(G.angleDiff(10, 350), 20);
  assert.equal(G.angleDiff(0, 180), 180);
  assert.equal(G.angleDiff(90, 90), 0);
  assert.equal(G.angleDiff(-30, 30), 60);
  assert.equal(G.angleDiff(359, 1), 2);
  assert.equal(G.angleDiff(720, 0), 0);
});

test("destination: round trip with distance and bearing", () => {
  const start = { lat: 31.2, lng: 16.6 };
  const p = G.destination(start, 45, 12345);
  near(G.distanceM(start, p), 12345, 0.5);
  near(G.bearingDeg(start, p), 45, 0.01);
});

test("isAhead: inside / outside the cone, wrap and short range", () => {
  assert.equal(G.isAhead(0, 30, 2000, 40, 150), true);
  assert.equal(G.isAhead(0, 40, 2000, 40, 150), true, "edge of the cone is inclusive");
  assert.equal(G.isAhead(0, 41, 2000, 40, 150), false);
  assert.equal(G.isAhead(350, 20, 2000, 40, 150), true, "wraps through north");
  assert.equal(G.isAhead(0, 180, 2000, 40, 150), false, "behind");
  assert.equal(G.isAhead(0, 180, 100, 40, 150), true, "closer than alwaysAheadM counts as ahead");
  assert.equal(G.isAhead(0, 180, 100, 40, 0), false);
});

test("inBox and validPoint", () => {
  const box = { min_lat: 19.5, max_lat: 33.5, min_lng: 9.3, max_lng: 25.2 };
  assert.equal(G.inBox(TRIPOLI, box), true);
  assert.equal(G.inBox({ lat: 19.5, lng: 9.3 }, box), true, "inclusive corner");
  assert.equal(G.inBox({ lat: 36.8, lng: 10.18 }, box), false, "Tunis");
  assert.equal(G.inBox(TRIPOLI, null), false);
  assert.equal(G.validPoint(TRIPOLI), true);
  assert.equal(G.validPoint({ lat: NaN, lng: 1 }), false);
  assert.equal(G.validPoint({ lat: 91, lng: 1 }), false);
  assert.equal(G.validPoint({ lat: "1", lng: 1 }), false);
  assert.equal(G.validPoint(null), false);
});
