"""Road sections (قواطع) and kilometre reference points."""
from ..extensions import db
from .base import TimestampMixin, TranslatableMixin, utcnow


class RoadSection(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = "road_sections"
    __table_args__ = (
        db.CheckConstraint("km_end >= km_start", name="km_range"),
        db.CheckConstraint("visibility_pct IS NULL OR (visibility_pct >= 0 AND visibility_pct <= 100)", name="visibility_range"),
    )

    STATUS_OPEN = "open"
    STATUS_PARTIAL = "partial"
    STATUS_CLOSED = "closed"
    STATUSES = (STATUS_OPEN, STATUS_PARTIAL, STATUS_CLOSED)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    km_start = db.Column(db.Numeric(7, 2), nullable=False)
    km_end = db.Column(db.Numeric(7, 2), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Operational condition (set by staff; shown on the public home screen)
    road_status = db.Column(db.String(16), nullable=False, default=STATUS_OPEN)
    visibility_pct = db.Column(db.SmallInteger)
    condition_updated_at = db.Column(db.DateTime, default=utcnow)

    translations = db.relationship(
        "RoadSectionTranslation", cascade="all, delete-orphan", lazy="selectin", back_populates="section"
    )

    def contains_km(self, km: float) -> bool:
        return float(self.km_start) <= km <= float(self.km_end)


class RoadSectionTranslation(db.Model):
    __tablename__ = "road_section_translations"
    __table_args__ = (db.UniqueConstraint("section_id", "locale", name="uq_section_locale"),)
    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey("road_sections.id", ondelete="CASCADE"), nullable=False)
    locale = db.Column(db.String(5), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    section = db.relationship("RoadSection", back_populates="translations")


class RoadPoint(db.Model):
    """Surveyed kilometre reference points (km ↔ lat/lng) used to convert GPS to a km marker.

    Accuracy of the GPS→km conversion depends entirely on the density and accuracy
    of these points; they must be loaded from the official road survey.
    """

    __tablename__ = "road_points"
    id = db.Column(db.Integer, primary_key=True)
    km = db.Column(db.Numeric(7, 2), nullable=False, unique=True)
    latitude = db.Column(db.Numeric(9, 6), nullable=False)
    longitude = db.Column(db.Numeric(9, 6), nullable=False)
    label = db.Column(db.String(120))
