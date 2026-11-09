"""Location helpers: GPS → kilometre marker → road section.

The conversion uses surveyed reference points (table `road_points`). The nearest
segment between two consecutive points is found and the position is projected on
it to interpolate the km value. If no reference points are configured, or the
user is farther than `MAX_OFFSET_KM` from the road, no km is returned (we never
fabricate a location).
"""
import math

from ..extensions import db
from ..models import RoadPoint, RoadSection

MAX_OFFSET_KM = 5.0
EARTH_R = 6371.0


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _project(lat, lng, a, b):
    """Project point on segment a→b using a local equirectangular approximation. Returns (t, distance_km)."""
    lat0 = math.radians((a[0] + b[0]) / 2)
    ax, ay = math.radians(a[1]) * math.cos(lat0) * EARTH_R, math.radians(a[0]) * EARTH_R
    bx, by = math.radians(b[1]) * math.cos(lat0) * EARTH_R, math.radians(b[0]) * EARTH_R
    px, py = math.radians(lng) * math.cos(lat0) * EARTH_R, math.radians(lat) * EARTH_R
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return t, math.hypot(px - cx, py - cy)


def km_from_coordinates(lat: float, lng: float):
    """Return (km, offset_km) or (None, None) when it cannot be determined reliably."""
    pts = db.session.execute(db.select(RoadPoint).order_by(RoadPoint.km)).scalars().all()
    if len(pts) < 2:
        return None, None
    best = None
    for a, b in zip(pts, pts[1:]):
        ca = (float(a.latitude), float(a.longitude))
        cb = (float(b.latitude), float(b.longitude))
        t, dist = _project(lat, lng, ca, cb)
        if best is None or dist < best[1]:
            km = float(a.km) + t * (float(b.km) - float(a.km))
            best = (km, dist)
    if best is None or best[1] > MAX_OFFSET_KM:
        return None, (best[1] if best else None)
    return round(best[0], 1), round(best[1], 2)


def coordinates_from_km(km: float):
    pts = db.session.execute(db.select(RoadPoint).order_by(RoadPoint.km)).scalars().all()
    for a, b in zip(pts, pts[1:]):
        if float(a.km) <= km <= float(b.km):
            span = float(b.km) - float(a.km) or 1
            t = (km - float(a.km)) / span
            return (
                float(a.latitude) + t * (float(b.latitude) - float(a.latitude)),
                float(a.longitude) + t * (float(b.longitude) - float(a.longitude)),
            )
    return None


def section_for_km(km):
    if km is None:
        return None
    return db.session.execute(
        db.select(RoadSection)
        .where(RoadSection.is_active.is_(True), RoadSection.km_start <= km, RoadSection.km_end >= km)
        .order_by(RoadSection.sort_order)
    ).scalars().first()


def road_polyline():
    pts = db.session.execute(db.select(RoadPoint).order_by(RoadPoint.km)).scalars().all()
    return [[float(p.latitude), float(p.longitude), float(p.km)] for p in pts]
