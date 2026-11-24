"""Driving mode: settings and the geographic query behind GET /api/v1/reports/nearby.

Privacy: the driver's position is used only to answer the request. It is never stored or logged.
All distance/heading/alert decisions are taken on the driver's device (static/js/drive-engine.js).
"""
from dataclasses import asdict, dataclass

from ..extensions import db
from ..models import Report, ReportStatus
from .geo import LIBYA_BBOX, bounding_box, haversine_km
from .settings import DEFAULT_SETTINGS, get_setting

MAX_FETCH_RADIUS_KM = 50
MAX_NEARBY_ITEMS = 300
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

    def client_dict(self) -> dict:
        """Values the driving page needs (no secrets)."""
        d = asdict(self)
        d.pop("alert_statuses")
        d["libya_bbox"] = LIBYA_BBOX.as_dict()
        return d


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
    return DriveConfig(
        enabled=bool(get_setting("drive_mode_enabled", True)),
        alert_statuses=parse_statuses(get_setting("drive_alert_statuses")),
        far_m=far,
        near_m=near,
        fetch_radius_km=_clamp_int("drive_fetch_radius_km", get_setting("drive_fetch_radius_km")),
        cone_deg=_clamp_int("drive_cone_deg", get_setting("drive_cone_deg")),
        refresh_s=_clamp_int("drive_refresh_s", get_setting("drive_refresh_s")),
    )


def validate_drive_settings(values: dict) -> list[str]:
    """Validate submitted driving settings (raw strings / lists). Returns the keys that are invalid."""
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
    far, near = values.get("drive_alert_far_m"), values.get("drive_alert_near_m")
    if far is not None and near is not None and "drive_alert_far_m" not in bad and "drive_alert_near_m" not in bad:
        if int(near) >= int(far):  # reject the pair together: never store an inconsistent combination
            bad.extend(["drive_alert_far_m", "drive_alert_near_m"])
    if "drive_alert_statuses" in values:
        st = values["drive_alert_statuses"]
        if not isinstance(st, (list, tuple)) or not st or any(s not in ALERTABLE_STATUS_CHOICES for s in st):
            bad.append("drive_alert_statuses")
    return bad


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
