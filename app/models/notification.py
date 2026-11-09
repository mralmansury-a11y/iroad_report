"""Notifications, preferences, web-push subscriptions and public announcements."""
import hashlib

from ..extensions import db
from .base import TimestampMixin, TranslatableMixin, current_locale, utcnow


class Notification(db.Model):
    """In-app notification. System text is generated in both languages at creation time."""

    __tablename__ = "notifications"
    __table_args__ = (db.Index("ix_notifications_user_read", "user_id", "is_read"),)

    KINDS = ("report_update", "assignment", "announcement", "weather", "project", "traffic", "emergency", "points", "admin")

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(24), nullable=False, default="admin")
    title_ar = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200), nullable=False)
    body_ar = db.Column(db.String(1000))
    body_en = db.Column(db.String(1000))
    url = db.Column(db.String(255))
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"))
    announcement_id = db.Column(db.Integer, db.ForeignKey("announcements.id", ondelete="CASCADE"))
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def title(self, locale=None):
        return self.title_en if (locale or current_locale()) == "en" else self.title_ar

    def body(self, locale=None):
        return self.body_en if (locale or current_locale()) == "en" else self.body_ar


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    report_updates = db.Column(db.Boolean, nullable=False, default=True)
    weather_alerts = db.Column(db.Boolean, nullable=False, default=True)
    project_updates = db.Column(db.Boolean, nullable=False, default=True)
    points_rewards = db.Column(db.Boolean, nullable=False, default=True)
    sound = db.Column(db.Boolean, nullable=False, default=False)
    push_enabled = db.Column(db.Boolean, nullable=False, default=True)
    user = db.relationship("User", backref=db.backref("notification_pref", uselist=False, cascade="all, delete-orphan"))

    def allows(self, kind: str) -> bool:
        mapping = {
            "report_update": self.report_updates,
            "assignment": True,
            "weather": self.weather_alerts,
            "traffic": self.weather_alerts,
            "project": self.project_updates,
            "announcement": self.project_updates,
            "points": self.points_rewards,
            "emergency": True,  # safety-critical: always delivered
            "admin": True,
        }
        return mapping.get(kind, True)


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)  # null = anonymous visitor (alerts only)
    endpoint = db.Column(db.Text, nullable=False)
    endpoint_hash = db.Column(db.String(64), nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    locale = db.Column(db.String(5), nullable=False, default="ar")
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_success_at = db.Column(db.DateTime)
    failure_count = db.Column(db.SmallInteger, nullable=False, default=0)

    @staticmethod
    def hash_endpoint(endpoint: str) -> str:
        return hashlib.sha256(endpoint.encode()).hexdigest()

    def as_webpush_info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


class Announcement(TranslatableMixin, TimestampMixin, db.Model):
    """Public road announcements: weather, traffic, closures, project news, emergencies."""

    __tablename__ = "announcements"
    KINDS = ("weather", "traffic", "project", "closure", "emergency", "general")

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False, default="general", index=True)
    km_from = db.Column(db.Numeric(7, 2))
    km_to = db.Column(db.Numeric(7, 2))
    road_section_id = db.Column(db.Integer, db.ForeignKey("road_sections.id", ondelete="SET NULL"))
    starts_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    ends_at = db.Column(db.DateTime)
    is_published = db.Column(db.Boolean, nullable=False, default=False, index=True)
    notified_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    translations = db.relationship(
        "AnnouncementTranslation", cascade="all, delete-orphan", lazy="selectin", back_populates="announcement"
    )
    road_section = db.relationship("RoadSection")
    created_by = db.relationship("User")

    @property
    def title(self):
        return self.tr("title")

    @property
    def body(self):
        return self.tr("body")

    @property
    def notification_kind(self) -> str:
        return {"weather": "weather", "traffic": "traffic", "project": "project", "closure": "traffic",
                "emergency": "emergency"}.get(self.kind, "announcement")


class AnnouncementTranslation(db.Model):
    __tablename__ = "announcement_translations"
    __table_args__ = (db.UniqueConstraint("announcement_id", "locale", name="uq_announcement_locale"),)
    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False)
    locale = db.Column(db.String(5), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    announcement = db.relationship("Announcement", back_populates="translations")
