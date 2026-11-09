"""Typed access to the `system_settings` table with safe defaults.

Secrets (DB password, SECRET_KEY, VAPID private key, SMTP password) are NEVER stored here;
they live only in the environment file.
"""
from flask import g, has_app_context

from ..extensions import db
from ..models import SystemSetting

# key: (default, type, is_public, description)
DEFAULT_SETTINGS = {
    "site_open_for_reports": ("true", "bool", True, "Accept new public reports"),
    "allow_guest_reports": ("true", "bool", True, "Allow reports without an account"),
    "nearby_radius_km": ("20", "int", True, "Radius (km) used for 'nearby reports'"),
    "stats_min_samples": ("3", "int", False, "Minimum records before showing an average"),
    "points_per_resolved": ("20", "int", True, "Contribution points when a report is resolved"),
    "points_per_accepted": ("0", "int", True, "Contribution points when a report is accepted for review"),
    "support_phone": ("", "str", True, "Public support phone"),
    "support_whatsapp": ("", "str", True, "Public WhatsApp number (international format, digits only)"),
    "support_email": ("", "str", True, "Public support e-mail"),
    "app_version": ("1.0.0", "str", True, "Displayed application version"),
    "privacy_updated": ("2026-08", "str", True, "Privacy policy last-updated (YYYY-MM)"),
    "default_map_lat": ("31.2089", "str", True, "Default map centre latitude"),
    "default_map_lng": ("16.5887", "str", True, "Default map centre longitude"),
    "default_map_zoom": ("8", "int", True, "Default map zoom"),
}


def get_setting(key: str, default=None):
    cache = g.setdefault("_settings_cache", {}) if _has_g() else {}
    if key in cache:
        return cache[key]
    row = db.session.execute(db.select(SystemSetting).filter_by(key=key)).scalar_one_or_none()
    if row is not None:
        val = row.typed()
    elif key in DEFAULT_SETTINGS:
        d, t, *_ = DEFAULT_SETTINGS[key]
        val = SystemSetting(key=key, value=d, value_type=t).typed()
    else:
        val = default
    if val is None:
        val = default
    cache[key] = val
    return val


def set_setting(key: str, value, user_id=None):
    row = db.session.execute(db.select(SystemSetting).filter_by(key=key)).scalar_one_or_none()
    if row is None:
        d, t, pub, desc = DEFAULT_SETTINGS.get(key, ("", "str", False, ""))
        row = SystemSetting(key=key, value_type=t, is_public=pub, description=desc)
        db.session.add(row)
    if isinstance(value, bool):
        value = "true" if value else "false"
    row.value = "" if value is None else str(value)
    row.updated_by_id = user_id
    if _has_g():
        g.pop("_settings_cache", None)
    return row


def _has_g() -> bool:
    return has_app_context()
