from flask import Blueprint
from flask_login import login_required

from ..services.rbac import staff_required

bp = Blueprint("admin", __name__)


@bp.before_request
@login_required
@staff_required
def _guard():
    """Every /admin route requires an authenticated, active staff account."""
    return None


from . import routes  # noqa: E402,F401
