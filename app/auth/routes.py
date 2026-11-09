from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import force_locale
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db, limiter
from ..models import Role, User, utcnow
from ..services.audit import audit
from ..services.mail import send_template
from ..utils import safe_next
from ..utils.validators import looks_like_email, normalize_phone
from . import bp
from .forms import ForgotForm, LoginForm, RegisterForm, ResetForm


def _find_user(identifier: str):
    ident = (identifier or "").strip()
    if looks_like_email(ident):
        return db.session.execute(db.select(User).filter(db.func.lower(User.email) == ident.lower())).scalar_one_or_none()
    phone = normalize_phone(ident)
    if phone:
        return db.session.execute(db.select(User).filter_by(phone=phone)).scalar_one_or_none()
    return None


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    form = LoginForm()
    if form.validate_on_submit():
        user = _find_user(form.identifier.data)
        if user is None or not user.check_password(form.password.data):
            audit("auth.login_failed", "user", user.id if user else None, identifier=form.identifier.data[:64])
            db.session.commit()
            flash(_("Incorrect login details."), "danger")
        elif not user.is_active:
            flash(_("This account is deactivated. Contact technical support."), "danger")
        else:
            session.clear()  # prevent session fixation
            login_user(user, remember=form.remember.data)
            user.last_login_at = utcnow()
            audit("auth.login", "user", user.id, user=user)
            db.session.commit()
            resp = redirect(safe_next(request.args.get("next"), url_for("admin.dashboard") if user.is_staff else url_for("main.home")))
            resp.set_cookie("lang", user.locale, max_age=31536000, samesite="Lax", secure=request.is_secure)
            return resp
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute; 30 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    form = RegisterForm()
    if form.validate_on_submit():
        phone = form.normalized_phone
        email = (form.email.data or "").strip().lower() or None
        if phone and db.session.execute(db.select(User.id).filter_by(phone=phone)).first():
            form.phone.errors.append(_("This phone number is already registered."))
        elif email and db.session.execute(db.select(User.id).filter(db.func.lower(User.email) == email)).first():
            form.email.errors.append(_("This e-mail is already registered."))
        else:
            from flask_babel import get_locale
            user = User(full_name=form.full_name.data.strip(), phone=phone, email=email,
                        locale=get_locale().language if get_locale() else "ar")
            user.set_password(form.password.data)
            public = db.session.execute(db.select(Role).filter_by(code=Role.PUBLIC)).scalar_one()
            user.roles.append(public)
            db.session.add(user)
            db.session.flush()
            audit("auth.register", "user", user.id, user=user)
            db.session.commit()
            session.clear()
            login_user(user)
            flash(_("Your account was created. Welcome!"), "success")
            return redirect(url_for("main.home"))
    return render_template("auth/register.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit("auth.logout", "user", current_user.id)
    db.session.commit()
    logout_user()
    session.clear()
    flash(_("You have been logged out."), "info")
    return redirect(url_for("main.home"))


# ------------------------------------------------------------ password reset
def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def notify_password_changed(user: User) -> None:
    """Security notice by e-mail after any password change (if the account has an e-mail)."""
    if not user.email:
        return
    from ..utils.i18n import fmt_dt
    with force_locale(user.locale or "ar"):
        send_template(user.email, _("Your password was changed — International Road Libya"), "password_changed",
                      user=user, when=fmt_dt(utcnow()))


def make_reset_token(user: User) -> str:
    return _serializer().dumps({"uid": user.id, "fp": user.password_hash[-12:]})


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot():
    form = ForgotForm()
    if form.validate_on_submit():
        user = _find_user(form.email.data)
        if user and user.email and user.is_active:
            link = url_for("auth.reset", token=make_reset_token(user), _external=True)
            with force_locale(user.locale or "ar"):  # e-mail in the account's language
                send_template(user.email, _("Password reset — International Road Libya"), "password_reset",
                              user=user, link=link, minutes=60)
            audit("auth.reset_requested", "user", user.id, user=user)
            db.session.commit()
        # identical response whether or not the account exists (no user enumeration)
        flash(_("If the e-mail is registered, a reset link has been sent."), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (SignatureExpired, BadSignature):
        flash(_("The reset link is invalid or has expired."), "danger")
        return redirect(url_for("auth.forgot"))
    user = db.session.get(User, data.get("uid"))
    if user is None or user.password_hash[-12:] != data.get("fp"):
        flash(_("The reset link is invalid or has expired."), "danger")
        return redirect(url_for("auth.forgot"))
    form = ResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        audit("auth.password_reset", "user", user.id, user=user)
        db.session.commit()
        notify_password_changed(user)
        flash(_("Your password was changed. You can log in now."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)
