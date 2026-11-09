"""Application factory for International Road Services – Libya (الطريق الدولي ليبيا)."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, g, request, session
from flask_login import current_user

from config import CONFIGS

from .extensions import babel, csrf, db, limiter, login_manager, migrate


def select_locale():
    langs = ("ar", "en")
    # 1) explicit ?lang=xx (used by the PWA start URL / shared links)
    q = request.args.get("lang")
    if q in langs:
        return q
    # 2) authenticated profile preference
    if current_user and getattr(current_user, "is_authenticated", False) and current_user.locale in langs:
        return current_user.locale
    # 3) visitor cookie / session
    c = request.cookies.get("lang") or session.get("lang")
    if c in langs:
        return c
    # 4) Arabic is the default for new visitors (by specification)
    return "ar"


def select_timezone():
    return None  # falls back to BABEL_DEFAULT_TIMEZONE (Africa/Tripoli)


def _resolve_instance_path(config_name: str) -> str:
    """Instance folder (writable runtime data).

    * INSTANCE_PATH from the environment always wins.
    * Production on Linux: /var/lib/irs-road/instance — writable under the systemd
      hardening (ProtectSystem=strict + ReadWritePaths=/var/lib/irs-road), and kept
      outside the release folders so it survives updates/rollbacks.
    * Development / tests / Windows: <project>/instance (no admin rights needed;
      Python 3.13 on Windows does not treat "/var/lib/..." as an absolute path).
    """
    env_path = os.environ.get("INSTANCE_PATH")
    if env_path:
        return str(Path(env_path).expanduser().resolve())
    if config_name == "production" and os.name == "posix":
        return "/var/lib/irs-road/instance"
    return str(Path(__file__).resolve().parent.parent / "instance")


def create_app(config_name: str | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_CONFIG") or os.environ.get("APP_ENV") or "production"
    app = Flask(
        __name__,
        instance_path=_resolve_instance_path(config_name),
        instance_relative_config=True,
    )
    app.config.from_object(CONFIGS[config_name])

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Configure it in the environment (.env).")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL is not set. Configure the MariaDB connection in the environment (.env).")
    if config_name == "production" and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        raise RuntimeError("SQLite is not allowed in production. Use MariaDB (mysql+pymysql://...).")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    # Behind Nginx: trust exactly one proxy hop for scheme/host/IP
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)
    babel.init_app(app, locale_selector=select_locale, timezone_selector=select_timezone)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None
    login_manager.session_protection = "strong"

    from . import models  # noqa: F401  (register models for migrations)

    @login_manager.user_loader
    def load_user(uid):
        return db.session.get(models.User, int(uid))

    @login_manager.request_loader
    def load_user_from_bearer(req):
        """Bearer token auth for /api/* (future native mobile apps)."""
        if not req.path.startswith("/api/"):
            return None
        auth = req.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        raw = auth.split(None, 1)[1].strip()
        tok = db.session.execute(
            db.select(models.ApiToken).filter_by(token_hash=models.ApiToken.hash(raw), revoked=False)
        ).scalar_one_or_none()
        if tok is None or tok.expires_at < models.utcnow() or not tok.user.is_active:
            return None
        tok.last_used_at = models.utcnow()
        g.api_token_auth = True
        return tok.user

    _register_blueprints(app)
    _register_template_helpers(app)
    _register_security(app)
    _register_errors(app)
    _configure_logging(app)

    from .cli import register_cli
    register_cli(app)
    return app


def _register_blueprints(app):
    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .notifications import bp as notif_bp
    from .reports import bp as reports_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(notif_bp, url_prefix="/notifications")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    # JSON API: session requests keep CSRF protection (header X-CSRFToken);
    # bearer-token requests are exempted inside the API blueprint.


def _register_template_helpers(app):
    from .utils import i18n as h

    app.jinja_env.filters.update(
        km=h.fmt_km, reltime=h.reltime, dt=h.fmt_dt, date=h.fmt_date, num=h.fmt_num,
        hours=h.fmt_hours, pct=h.fmt_pct,
    )
    app.jinja_env.globals.update(
        status_label=h.status_label, severity_label=h.severity_label, road_status_label=h.road_status_label,
        role_label=h.role_label, ann_kind_label=h.announcement_kind_label,
    )

    @app.context_processor
    def inject_globals():
        from flask_babel import get_locale

        from .models import Notification
        from .services.settings import get_setting

        loc = get_locale()
        lang = loc.language if loc else "ar"
        unread = 0
        if current_user.is_authenticated:
            unread = db.session.execute(
                db.select(db.func.count(Notification.id)).filter_by(user_id=current_user.id, is_read=False)
            ).scalar_one()
        theme = request.cookies.get("theme")
        return {
            "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr",
            "other_lang": "en" if lang == "ar" else "ar",
            "LANGUAGES": app.config["LANGUAGES"],
            "theme": theme if theme in ("light", "dark") else "dark",
            "unread_count": unread,
            "get_setting": get_setting,
            "vapid_public_key": app.config.get("VAPID_PUBLIC_KEY", ""),
            "js_i18n": h.js_strings(),
        }


def _register_security(app):
    # Allow map tiles from the configured tile server (MAP_TILE_URL) in the CSP.
    from urllib.parse import urlparse
    tile = urlparse(app.config.get("MAP_TILE_URL", "").replace("{s}.", "a."))
    host = tile.netloc
    if app.config.get("MAP_TILE_URL", "").find("{s}.") != -1 and host.startswith("a."):
        host = "*." + host[2:]
    tile_src = " ".join(dict.fromkeys(filter(None, [
        f"{tile.scheme}://{host}" if host else "", "https://tile.openstreetmap.org", "https://*.tile.openstreetmap.org"])))

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(self), microphone=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"img-src 'self' data: blob: {tile_src}; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
            "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if not app.debug and request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Never let shared caches store personalised pages
        private_prefixes = ("/admin", "/auth", "/api", "/notifications", "/profile", "/settings/notifications",
                            "/reports/attachment", "/reports/submitted", "/reports/track", "/reports/IR-")
        if current_user.is_authenticated or request.path.startswith(private_prefixes):
            resp.headers["Cache-Control"] = "no-store, private"
        elif "Cache-Control" not in resp.headers and resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-cache"  # public page: revalidate; SW may keep an offline copy
        return resp


def _register_errors(app):
    from flask import jsonify, render_template
    from flask_wtf.csrf import CSRFError

    def _wants_json():
        return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"

    def handler(code, key):
        def _h(e):
            if code >= 500:
                db.session.rollback()
                app.logger.exception("Server error: %s", e)
            if _wants_json():
                return jsonify({"ok": False, "error": {"code": key, "message": getattr(e, "description", key)}}), code
            return render_template("errors/error.html", code=code), code
        return _h

    for code, key in ((400, "bad_request"), (403, "forbidden"), (404, "not_found"), (405, "method_not_allowed"),
                      (413, "payload_too_large"), (429, "rate_limited"), (500, "server_error")):
        app.register_error_handler(code, handler(code, key))

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if _wants_json():
            return jsonify({"ok": False, "error": {"code": "csrf", "message": "CSRF token missing or invalid"}}), 400
        return render_template("errors/error.html", code=400, csrf=True), 400


def _configure_logging(app):
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    app.logger.setLevel(level)
    log_dir = os.environ.get("LOG_DIR")
    if log_dir and not app.testing:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(Path(log_dir) / "app.log", maxBytes=5 * 1024 * 1024, backupCount=10)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        fh.setLevel(level)
        app.logger.addHandler(fh)
