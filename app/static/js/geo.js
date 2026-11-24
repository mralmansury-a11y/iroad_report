/* Geodesy helpers for driving mode — PURE functions (no DOM, no globals, no I/O).
 * Shared by the web app (window.IRGeo) and Node tests / a future native wrapper (module.exports).
 * Points are plain objects {lat, lng} in decimal degrees (WGS-84). Angles are degrees, 0° = north, clockwise.
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.IRGeo = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const EARTH_RADIUS_M = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const toDeg = (r) => (r * 180) / Math.PI;

  /** Normalise any angle to [0, 360). */
  function normalizeDeg(deg) {
    const d = deg % 360;
    return d < 0 ? d + 360 : d;
  }

  /** Great-circle distance in metres (Haversine). */
  function distanceM(a, b) {
    const p1 = toRad(a.lat), p2 = toRad(b.lat);
    const dp = p2 - p1, dl = toRad(b.lng - a.lng);
    const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  /** Initial bearing from a to b in degrees [0, 360). */
  function bearingDeg(a, b) {
    const p1 = toRad(a.lat), p2 = toRad(b.lat), dl = toRad(b.lng - a.lng);
    const y = Math.sin(dl) * Math.cos(p2);
    const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return normalizeDeg(toDeg(Math.atan2(y, x)));
  }

  /** Smallest absolute difference between two bearings, in [0, 180] (handles the 0°/360° wrap). */
  function angleDiff(a, b) {
    const d = Math.abs(normalizeDeg(a) - normalizeDeg(b));
    return d > 180 ? 360 - d : d;
  }

  /** Point reached from `start` after `distance` metres on `bearing` (great circle). */
  function destination(start, bearing, distance) {
    const delta = distance / EARTH_RADIUS_M, theta = toRad(bearing);
    const p1 = toRad(start.lat), l1 = toRad(start.lng);
    const p2 = Math.asin(Math.sin(p1) * Math.cos(delta) + Math.cos(p1) * Math.sin(delta) * Math.cos(theta));
    const l2 = l1 + Math.atan2(Math.sin(theta) * Math.sin(delta) * Math.cos(p1), Math.cos(delta) - Math.sin(p1) * Math.sin(p2));
    return { lat: toDeg(p2), lng: ((toDeg(l2) + 540) % 360) - 180 };
  }

  /**
   * Is a target "ahead" of a driver moving on `heading`?
   * True when the bearing to the target is within ±coneDeg of the heading,
   * or the target is closer than `alwaysAheadM` (angles are meaningless at very short range).
   */
  function isAhead(heading, bearingToTarget, distance, coneDeg, alwaysAheadM) {
    if (distance <= (alwaysAheadM || 0)) return true;
    return angleDiff(heading, bearingToTarget) <= coneDeg;
  }

  /** Inclusive bounding-box test; box = {min_lat, max_lat, min_lng, max_lng}. */
  function inBox(p, box) {
    return !!box && p.lat >= box.min_lat && p.lat <= box.max_lat && p.lng >= box.min_lng && p.lng <= box.max_lng;
  }

  /** Finite, legal WGS-84 coordinates. */
  function validPoint(p) {
    return !!p && Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180;
  }

  return { EARTH_RADIUS_M, normalizeDeg, distanceM, bearingDeg, angleDiff, destination, isAhead, inBox, validPoint };
});
