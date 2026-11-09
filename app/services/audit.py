"""Audit logging for security-relevant and administrative actions."""
from flask import has_request_context, request
from flask_login import current_user

from ..extensions import db
from ..models import AuditLog


def audit(action: str, entity_type: str | None = None, entity_id=None, user=None, **details) -> AuditLog:
    uid = None
    if user is not None:
        uid = user.id
    elif has_request_context() and current_user.is_authenticated:
        uid = current_user.id
    ip = ua = None
    if has_request_context():
        ip = (request.headers.get("X-Real-IP") or request.remote_addr or "")[:45]
        ua = (request.user_agent.string or "")[:255]
    entry = AuditLog(
        user_id=uid,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or None,
        ip_address=ip,
        user_agent=ua,
    )
    db.session.add(entry)
    return entry
