"""Test fixtures.

The automated suite runs on an in-memory SQLite database for speed and isolation.
To run it against MariaDB (recommended before each release):
    TEST_DATABASE_URL="mysql+pymysql://irs_test:***@localhost/irs_test?charset=utf8mb4" pytest
"""
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import Role, Team, TeamMember, User  # noqa: E402
from app.seed import seed_demo, seed_reference  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")

    from flask import g

    @app.before_request
    def _isolate_request_globals():
        # The fixture keeps one app context open for the whole test (so tests can query the DB);
        # Flask then reuses it for every request. Clear per-request caches (locale, user, settings)
        # so each test request behaves like a real, independent HTTP request.
        for key in list(vars(g)):
            g.pop(key, None)
    with app.app_context():
        _db.create_all()
        seed_reference()
        seed_demo()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(role="public", phone=None, email=None, password="Passw0rd1", team=None, name="Test User"):
    u = User(full_name=name, phone=phone, email=email, locale="ar")
    u.set_password(password)
    u.roles.append(_db.session.execute(_db.select(Role).filter_by(code=role)).scalar_one())
    if team:
        u.team_memberships.append(TeamMember(team=_db.session.execute(_db.select(Team).filter_by(code=team)).scalar_one()))
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture()
def users(app):
    return {
        "public": make_user("public", phone="0921000001", name="Citizen"),
        "employee": make_user("employee", phone="0921000002", name="Field Tech", team="maintenance"),
        "employee2": make_user("employee", phone="0921000005", name="Other Tech", team="lighting"),
        "supervisor": make_user("supervisor", phone="0921000003", name="Supervisor"),
        "admin": make_user("admin", email="admin@example.ly", name="Admin"),
        "superadmin": make_user("superadmin", email="root@example.ly", name="Root"),
    }


def login(client, ident, password="Passw0rd1"):
    return client.post("/auth/login", data={"identifier": ident, "password": password}, follow_redirects=False)


def png_bytes(size=(64, 48), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf
