from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Notification, utcnow
from ..utils import safe_next

bp = Blueprint("notifications", __name__)


@bp.route("/")
@login_required
def index():
    page = max(1, request.args.get("page", 1, type=int))
    q = db.select(Notification).filter_by(user_id=current_user.id).order_by(Notification.created_at.desc())
    pagination = db.paginate(q, page=page, per_page=current_app.config["REPORTS_PER_PAGE"], error_out=False)
    return render_template("notifications/index.html", pagination=pagination)


@bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    db.session.execute(
        db.update(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=utcnow())
    )
    db.session.commit()
    return redirect(url_for("notifications.index"))


@bp.route("/<int:nid>/open", methods=["POST"])
@login_required
def open_one(nid):
    n = db.session.get(Notification, nid)
    if n is None or n.user_id != current_user.id:
        abort(404)
    if not n.is_read:
        n.is_read, n.read_at = True, utcnow()
        db.session.commit()
    return redirect(safe_next(n.url, url_for("notifications.index")))
