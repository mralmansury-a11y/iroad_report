"""Users, roles, permissions and API tokens."""
import hashlib
import secrets
from datetime import timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .base import TimestampMixin, utcnow

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<Permission {self.code}>"


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    level = db.Column(db.SmallInteger, nullable=False, default=0)  # higher = more privileged
    name_ar = db.Column(db.String(64), nullable=False)
    name_en = db.Column(db.String(64), nullable=False)
    permissions = db.relationship("Permission", secondary=role_permissions, lazy="selectin")

    PUBLIC = "public"
    EMPLOYEE = "employee"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

    def label(self, locale: str = "ar") -> str:
        return self.name_en if locale == "en" else self.name_ar

    def __repr__(self):
        return f"<Role {self.code}>"


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="contact_present"),
    )

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), unique=True)
    email = db.Column(db.String(255), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    locale = db.Column(db.String(5), nullable=False, default="ar")
    home_section_id = db.Column(db.Integer, db.ForeignKey("road_sections.id", ondelete="SET NULL"))
    job_title = db.Column(db.String(120))
    active = db.Column("is_active", db.Boolean, nullable=False, default=True, index=True)
    points = db.Column(db.Integer, nullable=False, default=0)
    last_login_at = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime, default=utcnow)

    roles = db.relationship("Role", secondary=user_roles, lazy="selectin")
    home_section = db.relationship("RoadSection", foreign_keys=[home_section_id])

    # ---- Flask-Login ----
    @property
    def is_active(self):  # type: ignore[override]
        return bool(self.active)

    # ---- passwords ----
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw, method="scrypt")
        self.password_changed_at = utcnow()

    def check_password(self, raw: str) -> bool:
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    # ---- RBAC ----
    def has_role(self, *codes: str) -> bool:
        return any(r.code in codes for r in self.roles)

    @property
    def role_level(self) -> int:
        return max((r.level for r in self.roles), default=0)

    @property
    def permission_codes(self) -> set[str]:
        codes: set[str] = set()
        for r in self.roles:
            codes.update(p.code for p in r.permissions)
        return codes

    def can(self, permission: str) -> bool:
        if self.has_role(Role.SUPERADMIN):
            return True
        return permission in self.permission_codes

    @property
    def is_staff(self) -> bool:
        return self.role_level >= 10

    @property
    def initials(self) -> str:
        parts = [p for p in (self.full_name or "").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:1]
        return f"{parts[0][:1]}.{parts[-1][:1]}"

    def primary_role(self):
        return max(self.roles, key=lambda r: r.level, default=None)

    def __repr__(self):
        return f"<User {self.id} {self.full_name}>"


class ApiToken(db.Model):
    """Bearer tokens for future native mobile clients. Only a SHA-256 hash is stored."""

    __tablename__ = "api_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    name = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime)
    revoked = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User")

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user: "User", ttl_days: int = 30, name: str | None = None) -> tuple["ApiToken", str]:
        raw = secrets.token_urlsafe(40)
        tok = cls(user=user, token_hash=cls.hash(raw), name=name, expires_at=utcnow() + timedelta(days=ttl_days))
        db.session.add(tok)
        return tok, raw
