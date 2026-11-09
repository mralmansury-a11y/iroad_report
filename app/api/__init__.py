"""JSON API v1.

Envelope: {"ok": true, "data": ...} or {"ok": false, "error": {"code": ..., "message": ...}}.
Auth: browser session (+ X-CSRFToken header for unsafe methods) or `Authorization: Bearer <token>`
(tokens from POST /api/v1/auth/token — intended for future Android/iOS apps).
"""
from flask import Blueprint, current_app, request, session

from ..extensions import csrf

bp = Blueprint("api", __name__)
csrf.exempt(bp)


@bp.before_request
def _bearer_is_token_only():
    """A request that presents a bearer token is authenticated by that token ONLY (never by a session cookie)."""
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        from flask import g, jsonify
        from flask_login import current_user
        session.pop("_user_id", None)  # ignore any ambient browser session
        if not current_user.is_authenticated or not g.get("api_token_auth"):
            if request.endpoint not in ("api.issue_token", "api.revoke_token"):
                return jsonify({"ok": False, "error": {"code": "invalid_token", "message": "Invalid or expired token"}}), 401


@bp.before_request
def _csrf_for_session_requests():
    if request.method in ("GET", "HEAD", "OPTIONS") or not current_app.config.get("WTF_CSRF_ENABLED", True):
        return
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        return  # token requests are not vulnerable to CSRF (no ambient credentials)
    if request.endpoint == "api.issue_token":
        return
    csrf.protect()


from . import routes  # noqa: E402,F401
