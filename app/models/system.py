"""System settings, audit log, contact messages and contribution points ledger."""
import json

from ..extensions import db
from .base import utcnow


class SystemSetting(db.Model):
    __tablename__ = "system_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), nullable=False, unique=True)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(8), nullable=False, default="str")  # str | int | bool | json
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    def typed(self):
        v = self.value
        if v is None:
            return None
        if self.value_type == "int":
            try:
                return int(v)
            except ValueError:
                return None
        if self.value_type == "bool":
            return v.lower() in ("1", "true", "yes", "on")
        if self.value_type == "json":
            try:
                return json.loads(v)
            except ValueError:
                return None
        return v


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    entity_type = db.Column(db.String(32), index=True)
    entity_id = db.Column(db.String(32))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    user = db.relationship("User")


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"
    STATUSES = ("new", "answered", "closed")
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    name = db.Column(db.String(120), nullable=False)
    contact = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(12), nullable=False, default="new", index=True)
    reply = db.Column(db.Text)
    handled_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    handled_at = db.Column(db.DateTime)
    user = db.relationship("User", foreign_keys=[user_id])
    handled_by = db.relationship("User", foreign_keys=[handled_by_id])


class PointsTransaction(db.Model):
    __tablename__ = "points_transactions"
    __table_args__ = (db.UniqueConstraint("user_id", "report_id", "reason", name="uq_points_once"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="SET NULL"))
    points = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
