"""Application configuration.

All secrets come from environment variables (see .env.example).
Never hard-code credentials in this file.
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    APP_NAME = "International Road Services – Libya"
    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    # --- Database (MariaDB via PyMySQL) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # --- Localization ---
    LANGUAGES = {"ar": "العربية", "en": "English"}
    BABEL_DEFAULT_LOCALE = "ar"
    BABEL_DEFAULT_TIMEZONE = os.environ.get("APP_TIMEZONE", "Africa/Tripoli")
    BABEL_TRANSLATION_DIRECTORIES = str(BASE_DIR / "translations")

    # --- Sessions / cookies ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "irs_session"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # --- CSRF ---
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # --- Uploads ---
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "25")) * 1024 * 1024
    MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_MB", "8")) * 1024 * 1024
    MAX_IMAGES_PER_REPORT = int(os.environ.get("MAX_IMAGES_PER_REPORT", "4"))
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}
    IMAGE_MAX_DIMENSION = 1920

    # --- Rate limiting ---
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = "600 per hour"

    # --- Web Push (VAPID) ---
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")  # base64url raw key or path to PEM
    VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:admin@example.ly")

    # --- Mail (password reset) ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", False)          # port 465 (implicit TLS)
    MAIL_VERIFY_TLS = _bool("MAIL_VERIFY_TLS", True)      # keep true for mail.iroad.ly
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "20"))
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@example.ly")
    MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "")
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")

    # --- Misc ---
    PREFERRED_URL_SCHEME = "https"
    REPORTS_PER_PAGE = 20
    ADMIN_PER_PAGE = 25
    API_TOKEN_TTL_DAYS = 30
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    MAP_TILE_URL = os.environ.get("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    MAP_ATTRIBUTION = os.environ.get(
        "MAP_ATTRIBUTION", '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    )


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-insecure-key-change-me"


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "testing-secret"
    # SQLite is used ONLY for the automated test-suite (in-memory, throwaway).
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
