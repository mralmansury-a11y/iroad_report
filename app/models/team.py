"""Operational teams and membership."""
from ..extensions import db
from .base import TimestampMixin, TranslatableMixin, utcnow


class Team(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = "teams"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    translations = db.relationship("TeamTranslation", cascade="all, delete-orphan", lazy="selectin", back_populates="team")
    members = db.relationship("TeamMember", cascade="all, delete-orphan", back_populates="team", lazy="selectin")


class TeamTranslation(db.Model):
    __tablename__ = "team_translations"
    __table_args__ = (db.UniqueConstraint("team_id", "locale", name="uq_team_locale"),)
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    locale = db.Column(db.String(5), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    team = db.relationship("Team", back_populates="translations")


class TeamMember(db.Model):
    __tablename__ = "team_members"
    __table_args__ = (db.UniqueConstraint("team_id", "user_id", name="uq_team_user"),)
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_leader = db.Column(db.Boolean, nullable=False, default=False)
    joined_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    team = db.relationship("Team", back_populates="members")
    user = db.relationship("User", backref=db.backref("team_memberships", cascade="all, delete-orphan"))
