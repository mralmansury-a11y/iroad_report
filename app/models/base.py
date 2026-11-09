"""Shared model helpers."""
from datetime import datetime, timezone

from flask_babel import get_locale

from ..extensions import db


def utcnow() -> datetime:
    """Naive UTC timestamp (all timestamps are stored in UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_locale() -> str:
    try:
        loc = get_locale()
        return loc.language if loc else "ar"
    except Exception:  # outside request context
        return "ar"


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class TranslatableMixin:
    """Mixin for entities whose labels live in a `<entity>_translations` table.

    Subclasses define a `translations` relationship (one row per locale).
    `obj.tr("name")` returns the label for the active locale, falling back to
    Arabic, then to any available translation, then to the entity code.
    """

    def _translation_for(self, locale: str):
        for t in self.translations:
            if t.locale == locale:
                return t
        return None

    def tr(self, field: str = "name", locale: str | None = None) -> str:
        locale = locale or current_locale()
        for loc in (locale, "ar", "en"):
            t = self._translation_for(loc)
            if t is not None and getattr(t, field, None):
                return getattr(t, field)
        for t in self.translations:
            if getattr(t, field, None):
                return getattr(t, field)
        return getattr(self, "code", "") or ""

    def set_translation(self, locale: str, **fields):
        t = self._translation_for(locale)
        if t is None:
            t = type(self).translations.property.mapper.class_(locale=locale)  # type: ignore[attr-defined]
            self.translations.append(t)
        for k, v in fields.items():
            setattr(t, k, v)
        return t

    @property
    def name(self) -> str:  # convenience for templates
        return self.tr("name")
