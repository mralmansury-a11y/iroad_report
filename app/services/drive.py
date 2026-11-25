"""Driving mode: settings and the geographic query behind POST /api/v1/reports/nearby.

Privacy: the driver's position is used only to answer the request. It travels in the request body
(never in the URL), so it is neither stored nor written to the nginx/gunicorn access logs.
All distance/heading/alert decisions are taken on the driver's device (static/js/drive-engine.js).
"""
import math
from dataclasses import asdict, dataclass

from ..extensions import db
from ..models import Report, ReportStatus
from .geo import LIBYA_BBOX, bounding_box, haversine_km
from .settings import DEFAULT_SETTINGS, get_setting

MAX_FETCH_RADIUS_KM = 50
MAX_NEARBY_ITEMS = 300
# Upper bound of the full list a device downloads and keeps for offline use (GET /reports/alertable).
MAX_OFFLINE_ITEMS = 3000
# The client fetches the list again after driving refresh_dist_m. At that point the fetched circle
# must still cover the far-alert distance ahead: fetch_radius_m >= far_m + refresh_dist_m.
MIN_REFETCH_M = 1000
MAX_REFETCH_M = 10000
# Statuses that may be configured as "verified by the administration".
# Final statuses (resolved/rejected) can never trigger an alert.
ALERTABLE_STATUS_CHOICES = (ReportStatus.NEW, ReportStatus.UNDER_REVIEW, ReportStatus.ASSIGNED, ReportStatus.IN_PROGRESS)
DEFAULT_ALERT_STATUSES = (ReportStatus.ASSIGNED, ReportStatus.IN_PROGRESS)

# key: (min, max) inclusive ranges accepted from the control panel
INT_RANGES = {
    "drive_alert_far_m": (200, 20000),
    "drive_alert_near_m": (50, 5000),
    "drive_fetch_radius_km": (1, MAX_FETCH_RADIUS_KM),
    "drive_cone_deg": (5, 90),
    "drive_refresh_s": (30, 3600),
}


@dataclass(frozen=True)
class DriveConfig:
    enabled: bool
    alert_statuses: tuple[str, ...]
    far_m: int
    near_m: int
    fetch_radius_km: int
    cone_deg: int
    refresh_s: int

    @property
    def refresh_dist_m(self) -> int:
        """Distance driven before the list is fetched again (keeps far_m ahead inside the fetched circle)."""
        return max(MIN_REFETCH_M, min(MAX_REFETCH_M, self.fetch_radius_km * 1000 - self.far_m))

    def client_dict(self) -> dict:
        """Values the driving page needs (no secrets)."""
        d = asdict(self)
        d.pop("alert_statuses")
        d["refresh_dist_m"] = self.refresh_dist_m
        d["libya_bbox"] = LIBYA_BBOX.as_dict()
        return d


def min_fetch_radius_km(far_m: int) -> int:
    """Smallest fetch radius that covers far_m ahead plus the minimum refetch distance."""
    return math.ceil((far_m + MIN_REFETCH_M) / 1000)


def _clamp_int(key: str, value) -> int:
    lo, hi = INT_RANGES[key]
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = int(DEFAULT_SETTINGS[key][0])
    return max(lo, min(hi, v))


def parse_statuses(value) -> tuple[str, ...]:
    """Keep only known, non-final status codes (order preserved, duplicates removed)."""
    if not isinstance(value, (list, tuple)):
        return DEFAULT_ALERT_STATUSES
    return tuple(dict.fromkeys(s for s in value if s in ALERTABLE_STATUS_CHOICES))


def drive_config() -> DriveConfig:
    """Current driving-mode settings, defensively clamped (a bad DB value can never break the page)."""
    far = _clamp_int("drive_alert_far_m", get_setting("drive_alert_far_m"))
    near = _clamp_int("drive_alert_near_m", get_setting("drive_alert_near_m"))
    if near >= far:  # the near stage must come after the far stage
        near = max(INT_RANGES["drive_alert_near_m"][0], far // 10)
    radius = max(_clamp_int("drive_fetch_radius_km", get_setting("drive_fetch_radius_km")), min_fetch_radius_km(far))
    return DriveConfig(
        enabled=bool(get_setting("drive_mode_enabled", True)),
        alert_statuses=parse_statuses(get_setting("drive_alert_statuses")),
        far_m=far,
        near_m=near,
        fetch_radius_km=radius,
        cone_deg=_clamp_int("drive_cone_deg", get_setting("drive_cone_deg")),
        refresh_s=_clamp_int("drive_refresh_s", get_setting("drive_refresh_s")),
    )


def validate_drive_settings(values: dict, current: dict | None = None) -> list[str]:
    """Validate submitted driving settings (raw strings / lists). Returns the keys that are invalid.

    Cross-field rules use the values in effect after saving: the submitted value when it is valid,
    otherwise the stored one from `current` (defaults when not given). When a rule fails, every
    submitted key of that rule is rejected, so an inconsistent combination is never stored.
    """
    bad = []
    for key, (lo, hi) in INT_RANGES.items():
        if key not in values:
            continue
        try:
            v = int(values[key])
        except (TypeError, ValueError):
            bad.append(key)
            continue
        if not lo <= v <= hi:
            bad.append(key)
    current = current or {}

    def effective(key):
        raw = values[key] if key in values and key not in bad else current.get(key, DEFAULT_SETTINGS[key][0])
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(DEFAULT_SETTINGS[key][0])

    def check(keys, ok):
        if not ok:
            bad.extend(k for k in keys if k in values and k not in bad)

    check(("drive_alert_far_m", "drive_alert_near_m"), effective("drive_alert_near_m") < effective("drive_alert_far_m"))
    check(("drive_fetch_radius_km", "drive_alert_far_m"),
          effective("drive_fetch_radius_km") >= min_fetch_radius_km(effective("drive_alert_far_m")))
    if "drive_alert_statuses" in values:
        st = values["drive_alert_statuses"]
        if not isinstance(st, (list, tuple)) or not st or any(s not in ALERTABLE_STATUS_CHOICES for s in st):
            bad.append("drive_alert_statuses")
    return bad


def alertable_reports(statuses) -> list[Report]:
    """Every report in the alertable statuses inside Libya (most recently updated first, capped).

    Public data only. The device stores this list and filters it locally, so driving mode keeps
    working offline and the server never receives the driver's position.
    """
    if not statuses:
        return []
    q = (db.select(Report).join(ReportStatus)
         .where(ReportStatus.code.in_(list(statuses)),
                Report.latitude.between(LIBYA_BBOX.min_lat, LIBYA_BBOX.max_lat),
                Report.longitude.between(LIBYA_BBOX.min_lng, LIBYA_BBOX.max_lng))
         .order_by(Report.updated_at.desc(), Report.id.desc())
         .limit(MAX_OFFLINE_ITEMS))
    return list(db.session.execute(q).scalars())


def nearby_alertable_reports(lat: float, lng: float, radius_km: float, statuses) -> list[tuple[Report, float]]:
    """Reports in the alertable statuses within `radius_km`, nearest first, as (report, distance_km).

    1) bounding-box pre-filter on (latitude, longitude) — served by ix_reports_lat_lng;
    2) exact great-circle filter in Python.
    """
    if not statuses:
        return []
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    q = (db.select(Report).join(ReportStatus)
         .where(ReportStatus.code.in_(list(statuses)),
                Report.latitude.is_not(None), Report.longitude.is_not(None),
                Report.latitude.between(min_lat, max_lat), Report.longitude.between(min_lng, max_lng)))
    found = []
    for r in db.session.execute(q).scalars():
        d = haversine_km(lat, lng, float(r.latitude), float(r.longitude))
        if d <= radius_km:
            found.append((r, d))
    found.sort(key=lambda x: x[1])
    return found[:MAX_NEARBY_ITEMS]
