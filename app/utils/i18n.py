"""Locale-aware formatting helpers and system labels.

Conventions (documented in docs/LOCALIZATION.md):
* Western (Latin) digits are used in both languages, as in the Libyan locale and the
  majority of the Figma screens — this removes the mixed-digit inconsistency in the design.
* Kilometre markers: Arabic «214 كم», English «km 214».
* All timestamps are stored in UTC and rendered in Africa/Tripoli.
"""
from datetime import datetime

from flask_babel import format_datetime, format_decimal, format_timedelta, get_locale
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from ..models.base import utcnow


def _lang():
    loc = get_locale()
    return loc.language if loc else "ar"


def fmt_num(v, digits: int = 0):
    if v is None:
        return "—"
    fmt = "#,##0" + ("." + "#" * digits if digits else "")
    return format_decimal(float(v), format=fmt)


def fmt_km(v):
    if v is None:
        return "—"
    n = fmt_num(v, 1)
    return f"{n} كم" if _lang() == "ar" else f"km {n}"


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{int(v)}%"


def fmt_hours(h):
    if h is None:
        return "—"
    if h < 1:
        m = max(1, round(h * 60))
        return _("%(n)s min", n=m)
    if h < 48:
        return _("%(n)s h", n=fmt_num(h, 1 if h < 10 else 0))
    return _("%(n)s d", n=fmt_num(h / 24, 1))


def reltime(dt: datetime | None):
    if dt is None:
        return ""
    delta = dt - utcnow()
    if abs(delta.total_seconds()) < 60:
        return _("just now")
    return format_timedelta(delta, add_direction=True, threshold=0.9)


def fmt_dt(dt, fmt="medium"):
    return format_datetime(dt, fmt) if dt else "—"


def fmt_date(dt, fmt="d MMMM y"):
    return format_datetime(dt, fmt) if dt else "—"


# ------------------------------------------------------------ system labels
SEVERITY_LABELS = {"low": _l("Minor"), "medium": _l("Moderate"), "high": _l("Serious")}
ROAD_STATUS_LABELS = {"open": _l("Road open"), "partial": _l("Partially open"), "closed": _l("Road closed")}
ANNOUNCEMENT_KINDS = {
    "weather": _l("Weather alert"), "traffic": _l("Expected congestion"), "project": _l("Project update"),
    "closure": _l("Road closure"), "emergency": _l("Emergency"), "general": _l("Announcement"),
}


def status_label(status) -> str:
    return status.tr("name") if status is not None else ""


def severity_label(code: str) -> str:
    return str(SEVERITY_LABELS.get(code, code))


def road_status_label(code: str | None) -> str:
    return str(ROAD_STATUS_LABELS.get(code, "—")) if code else "—"


def announcement_kind_label(code: str) -> str:
    return str(ANNOUNCEMENT_KINDS.get(code, code))


def role_label(role) -> str:
    return role.label(_lang()) if role else ""


def drive_js_strings() -> dict:
    """Strings for the driving-mode page only. Placeholders use {name} and are filled in JavaScript."""
    return {
        "unitM": _("m"),
        "unitKm": _("km"),
        "spokenM": _("metres"),
        "spokenKm": _("kilometres"),
        "tripSummary": _("%(n)s verified hazards are known within %(r)s km of you.", n="{n}", r="{radius}"),
        "tripSummaryNone": _("No verified hazards are known within %(r)s km of you.", r="{radius}"),
        "alertFar": _("Caution: %(category)s ahead in %(distance)s. Severity: %(severity)s.",
                      category="{category}", distance="{distance}", severity="{severity}"),
        "alertNear": _("Warning! %(category)s in %(distance)s.", category="{category}", distance="{distance}"),
        "noHazardAhead": _("No reported hazards ahead"),
        "gpsWaiting": _("Waiting for GPS…"),
        "gpsWaitingFor": _("Waiting for an accurate GPS fix… %(n)s s", n="{n}"),
        "gpsSlowHint": _("Make sure location (GPS) is on and you are outdoors with a clear view of the sky. "
                         "Most computers have no GPS: use a phone."),
        "gpsApprox": _("Approximate location (±%(n)s m). Alerts start once an accurate GPS fix is received.", n="{n}"),
        "gpsApproxShort": _("Approx. ±%(n)s m", n="{n}"),
        "gpsUnavailable": _("Location is unavailable. Turn on location services (GPS) on this device. Still trying…"),
        "gpsAccuracy": _("GPS ±%(n)s m", n="{n}"),
        "gpsWeak": _("Weak GPS signal (±%(n)s m). Alerts are paused.", n="{n}"),
        "outsideLibya": _("You are outside Libya. Alerts are paused."),
        "headingUnknown": _("Start moving to determine the driving direction."),
        "updatedJustNow": _("Reports updated just now"),
        "updatedMinutes": _("Reports updated %(n)s min ago", n="{n}"),
        "updatedHours": _("Reports updated %(n)s h ago", n="{n}"),
        "updatedDays": _("Reports updated %(n)s days ago", n="{n}"),
        "usingSaved": _("No internet: using the %(n)s reports saved on this device.", n="{n}"),
        "noSavedReports": _("No reports are saved on this device yet. Connect to the internet once to download them."),
        "updateFailed": _("Could not update the reports. The last list is shown."),
        "notUpdated": _("Reports not loaded yet"),
        "online": _("Online"),
        "offline": _("Offline"),
        "wakeLockUnsupported": _("This browser cannot keep the screen on. Turn off auto-lock manually."),
        "notificationTitle": _("Driving mode"),
        "tripEnded": _("Trip ended."),
        "simNoReports": _("No eligible reports near the start point: simulating a straight drive."),
    }


def js_strings() -> dict:
    """Strings needed by client-side JavaScript, translated server-side."""
    return {
        "offline": _("You are offline. Some features are unavailable."),
        "online": _("Back online."),
        "locating": _("Locating…"),
        "locationDenied": _("Location access is blocked for this site. Allow it from the browser settings (lock icon next to the address) and try again."),
        "locationInsecure": _("The browser allows location only over a secure connection (HTTPS)."),
        "locationUnsupported": _("This browser does not support location services."),
        "locationTimeout": _("Locating took too long. Make sure location (GPS) is turned on and try again."),
        "locatingHint": _("Allow location access if the browser asks."),
        "locationNotSet": _("Location not set yet"),
        "locationRequired": _("Set the location with “Use my location” or “Pick on map”."),
        "orPickOnMap": _("You can also pick the point on the map."),
        "locationFromGps": _("Your current location was set"),
        "locationFromMap": _("The point chosen on the map was set"),
        "locationOffRoadKept": _("The location was saved. It is outside the surveyed road points, so the kilometre will be set by the road team."),
        "locationSavedOffline": _("Coordinates saved. The kilometre will be calculated when the report is sent."),
        "dragMarker": _("Drag to adjust the location"),
        "mapUnavailable": _("The map could not be loaded. Use “Use my location”."),
        "locationUnavailable": _("Your location could not be determined. Choose it manually."),
        "locationOffRoad": _("You appear to be away from the International Road. Choose the location manually."),
        "autoDetected": _("Detected automatically, you can edit it"),
        "km": _("km"),
        "youAreHere": _("You are here"),
        "draftSaved": _("Draft saved on this device."),
        "draftRestored": _("An unsent draft was restored."),
        "offlineSubmit": _("You are offline. The report was NOT sent; it is saved as a draft. Send it when you are back online."),
        "sending": _("Sending…"),
        "networkError": _("Network error. Please try again."),
        "tooManyImages": _("Too many images."),
        "pushEnabled": _("Notifications enabled on this device."),
        "pushDenied": _("Notification permission was denied in the browser."),
        "pushUnsupported": _("This browser does not support push notifications."),
        "installIos": _("On iPhone: tap Share, then “Add to Home Screen”."),
        "updateReady": _("A new version is available."),
        "reload": _("Update"),
        "confirm": _("Are you sure?"),
        "removeImage": _("Remove image"),
        "noData": _("Not enough data yet"),
        "reports": _("Reports"),
        "resolved": _("Resolved"),
    }
