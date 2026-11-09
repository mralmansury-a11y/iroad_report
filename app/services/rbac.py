"""Role-based access control: permission catalogue, role definitions and decorators."""
from functools import wraps

from flask import abort, request, jsonify
from flask_login import current_user

PERMISSIONS = {
    "reports.view_assigned": "View reports assigned to me or my team",
    "reports.update_status": "Change report status (employees: assigned reports only)",
    "reports.internal_notes": "Read and write internal notes",
    "reports.view_all": "View every report",
    "reports.review": "Review / classify / reject reports",
    "reports.assign": "Assign reports to teams and employees",
    "analytics.view": "View analytics",
    "announcements.manage": "Publish road announcements and alerts",
    "messages.manage": "Handle contact/support messages",
    "sections.manage": "Manage road sections and road condition",
    "users.view": "View users",
    "users.manage": "Create / edit / deactivate users",
    "employees.manage": "Manage employees and team membership",
    "teams.manage": "Manage teams",
    "categories.manage": "Manage report categories",
    "settings.manage": "Manage system settings",
    "audit.view": "View audit logs",
    "roles.manage": "Grant administrator roles",
}

_EMPLOYEE = ["reports.view_assigned", "reports.update_status", "reports.internal_notes"]
_SUPERVISOR = _EMPLOYEE + [
    "reports.view_all", "reports.review", "reports.assign", "analytics.view",
    "announcements.manage", "messages.manage", "sections.manage", "users.view",
]
_ADMIN = _SUPERVISOR + [
    "users.manage", "employees.manage", "teams.manage", "categories.manage", "settings.manage", "audit.view",
]

# code: (level, name_ar, name_en, permissions)
ROLE_DEFS = {
    "public": (0, "مستخدم", "Public user", []),
    "employee": (10, "موظف", "Employee", _EMPLOYEE),
    "supervisor": (20, "مشرف", "Supervisor", _SUPERVISOR),
    "admin": (30, "مسؤول النظام", "Administrator", _ADMIN),
    "superadmin": (40, "مسؤول أعلى", "Super administrator", list(PERMISSIONS)),
}


def can_grant_role(actor, role) -> bool:
    """An actor may only grant roles strictly below their own level (superadmin: any)."""
    if actor.has_role("superadmin"):
        return True
    return role.level < actor.role_level


def _deny():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": {"code": "forbidden", "message": "Forbidden"}}), 403
    abort(403)


def permission_required(*perms: str, any_of: bool = False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": {"code": "unauthorized", "message": "Login required"}}), 401
                from flask import redirect, url_for
                return redirect(url_for("auth.login", next=request.full_path))
            checks = [current_user.can(p) for p in perms]
            if (any_of and not any(checks)) or (not any_of and not all(checks)):
                return _deny()
            return view(*args, **kwargs)

        return wrapped

    return decorator


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            from flask import redirect, url_for
            return redirect(url_for("auth.login", next=request.full_path))
        if not current_user.is_staff:
            return _deny()
        return view(*args, **kwargs)

    return wrapped
