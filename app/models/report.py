"""Road incident reports and their workflow."""
from ..extensions import db
from .base import TimestampMixin, TranslatableMixin, utcnow


class ReportCategory(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = "report_categories"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    icon = db.Column(db.String(48), nullable=False, default="bi-exclamation-triangle")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    default_team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"))
    translations = db.relationship(
        "ReportCategoryTranslation", cascade="all, delete-orphan", lazy="selectin", back_populates="category"
    )
    default_team = db.relationship("Team")


class ReportCategoryTranslation(db.Model):
    __tablename__ = "report_category_translations"
    __table_args__ = (db.UniqueConstraint("category_id", "locale", name="uq_category_locale"),)
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("report_categories.id", ondelete="CASCADE"), nullable=False)
    locale = db.Column(db.String(5), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    category = db.relationship("ReportCategory", back_populates="translations")


class ReportStatus(TranslatableMixin, db.Model):
    __tablename__ = "report_statuses"
    NEW = "new"
    UNDER_REVIEW = "under_review"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    ALL = (NEW, UNDER_REVIEW, ASSIGNED, IN_PROGRESS, RESOLVED, REJECTED)
    OPEN = (NEW, UNDER_REVIEW, ASSIGNED, IN_PROGRESS)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(24), nullable=False, unique=True)
    sort_order = db.Column(db.SmallInteger, nullable=False, default=0)
    tone = db.Column(db.String(16), nullable=False, default="neutral")  # css token: new/review/assigned/progress/done/rejected
    is_final = db.Column(db.Boolean, nullable=False, default=False)
    translations = db.relationship(
        "ReportStatusTranslation", cascade="all, delete-orphan", lazy="selectin", back_populates="status"
    )


class ReportStatusTranslation(db.Model):
    __tablename__ = "report_status_translations"
    __table_args__ = (db.UniqueConstraint("status_id", "locale", name="uq_status_locale"),)
    id = db.Column(db.Integer, primary_key=True)
    status_id = db.Column(db.Integer, db.ForeignKey("report_statuses.id", ondelete="CASCADE"), nullable=False)
    locale = db.Column(db.String(5), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    status = db.relationship("ReportStatus", back_populates="translations")


class Report(TimestampMixin, db.Model):
    __tablename__ = "reports"
    __table_args__ = (
        db.CheckConstraint("severity IN ('low','medium','high')", name="severity_values"),
        db.CheckConstraint("km_marker IS NULL OR km_marker >= 0", name="km_positive"),
        db.CheckConstraint("latitude IS NULL OR (latitude BETWEEN -90 AND 90)", name="lat_range"),
        db.CheckConstraint("longitude IS NULL OR (longitude BETWEEN -180 AND 180)", name="lng_range"),
        db.Index("ix_reports_status_created", "status_id", "created_at"),
        db.Index("ix_reports_section_km", "road_section_id", "km_marker"),
    )

    SEVERITIES = ("low", "medium", "high")

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(24), unique=True)  # e.g. IR-2026-000123 (set after insert)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    language = db.Column(db.String(5), nullable=False, default="ar")  # language of user-submitted text
    category_id = db.Column(db.Integer, db.ForeignKey("report_categories.id"), nullable=False, index=True)
    status_id = db.Column(db.Integer, db.ForeignKey("report_statuses.id"), nullable=False, index=True)
    severity = db.Column(db.String(8), nullable=False, default="medium", index=True)

    km_marker = db.Column(db.Numeric(7, 2), index=True)
    road_section_id = db.Column(db.Integer, db.ForeignKey("road_sections.id", ondelete="SET NULL"), index=True)
    latitude = db.Column(db.Numeric(9, 6))
    longitude = db.Column(db.Numeric(9, 6))
    location_source = db.Column(db.String(8), nullable=False, default="manual")  # gps | manual | map

    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    guest_name = db.Column(db.String(120))
    guest_phone = db.Column(db.String(20))

    assigned_team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)

    first_response_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    points_awarded = db.Column(db.Boolean, nullable=False, default=False)

    category = db.relationship("ReportCategory", lazy="joined")
    status = db.relationship("ReportStatus", lazy="joined")
    road_section = db.relationship("RoadSection", lazy="joined")
    reporter = db.relationship("User", foreign_keys=[reporter_id], backref="reports")
    assigned_team = db.relationship("Team", foreign_keys=[assigned_team_id])
    assigned_user = db.relationship("User", foreign_keys=[assigned_user_id])
    attachments = db.relationship("ReportAttachment", cascade="all, delete-orphan", back_populates="report", lazy="selectin")
    history = db.relationship(
        "ReportStatusHistory", cascade="all, delete-orphan", back_populates="report",
        order_by="(ReportStatusHistory.created_at, ReportStatusHistory.id)",
    )
    notes = db.relationship("ReportNote", cascade="all, delete-orphan", back_populates="report", order_by="(ReportNote.created_at, ReportNote.id)")
    assignments = db.relationship(
        "EmployeeAssignment", cascade="all, delete-orphan", back_populates="report", order_by="EmployeeAssignment.assigned_at"
    )

    @property
    def status_code(self) -> str:
        return self.status.code if self.status else ReportStatus.NEW

    @property
    def is_open(self) -> bool:
        return self.status_code in ReportStatus.OPEN

    def km_float(self):
        return float(self.km_marker) if self.km_marker is not None else None


class ReportStatusHistory(db.Model):
    __tablename__ = "report_status_history"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status_id = db.Column(db.Integer, db.ForeignKey("report_statuses.id"))
    to_status_id = db.Column(db.Integer, db.ForeignKey("report_statuses.id"), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    public_note = db.Column(db.String(1000))   # visible to the reporter
    internal_note = db.Column(db.String(2000))  # staff only
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    report = db.relationship("Report", back_populates="history")
    from_status = db.relationship("ReportStatus", foreign_keys=[from_status_id])
    to_status = db.relationship("ReportStatus", foreign_keys=[to_status_id])
    changed_by = db.relationship("User")


class ReportNote(db.Model):
    """Staff notes. `is_internal=False` notes are shown to the reporter as official responses."""

    __tablename__ = "report_notes"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    report = db.relationship("Report", back_populates="notes")
    author = db.relationship("User")


class ReportAttachment(db.Model):
    __tablename__ = "report_attachments"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_name = db.Column(db.String(80), nullable=False, unique=True)  # random, server generated
    original_name = db.Column(db.String(255))
    mime_type = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    report = db.relationship("Report", back_populates="attachments")


class EmployeeAssignment(db.Model):
    __tablename__ = "employee_assignments"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    note = db.Column(db.String(1000))
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    assigned_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    completed_at = db.Column(db.DateTime)

    report = db.relationship("Report", back_populates="assignments")
    team = db.relationship("Team")
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id])
