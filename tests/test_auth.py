from app.extensions import db
from app.models import AuditLog, User

from .conftest import login


def test_register_login_logout(client, app):
    r = client.post("/auth/register", data={
        "full_name": "يوسف القناشي", "phone": "092-1234567", "email": "", "password": "Secret123",
        "confirm": "Secret123", "accept": "y"})
    assert r.status_code == 302
    u = db.session.execute(db.select(User).filter_by(phone="0921234567")).scalar_one()
    assert u.password_hash != "Secret123" and u.password_hash.startswith("scrypt:")
    assert u.has_role("public") and not u.is_staff
    client.post("/auth/logout")
    assert client.get("/profile").status_code == 302  # logged out
    r = login(client, "+218 92 1234567", "Secret123")  # phone normalisation
    assert r.status_code == 302
    assert client.get("/profile").status_code == 200


def test_register_validation(client):
    r = client.post("/auth/register", data={"full_name": "AB", "password": "short", "confirm": "x"})
    assert r.status_code == 200
    assert db.session.execute(db.select(User).filter_by(full_name="AB")).first() is None


def test_duplicate_phone_rejected(client, users):
    r = client.post("/auth/register", data={"full_name": "Someone", "phone": "0921000001", "password": "Secret123",
                                            "confirm": "Secret123", "accept": "y"})
    assert r.status_code == 200
    assert db.session.execute(db.select(db.func.count(User.id)).filter_by(phone="0921000001")).scalar_one() == 1


def test_wrong_password_and_audit(client, users):
    r = login(client, "0921000001", "WrongPass1")
    assert r.status_code == 200
    assert db.session.execute(db.select(AuditLog).filter_by(action="auth.login_failed")).first() is not None


def test_deactivated_user_cannot_login(client, users):
    users["public"].active = False
    db.session.commit()
    r = login(client, "0921000001")
    assert r.status_code == 200
    assert client.get("/profile").status_code == 302


def test_password_reset_token(client, users, app):
    from app.auth.routes import make_reset_token
    u = users["admin"]
    with app.test_request_context():
        tok = make_reset_token(u)
    r = client.post(f"/auth/reset/{tok}", data={"password": "NewPass123", "confirm": "NewPass123"})
    assert r.status_code == 302
    # token is single-use (fingerprint of old hash no longer matches)
    r = client.post(f"/auth/reset/{tok}", data={"password": "Other1234", "confirm": "Other1234"})
    assert r.status_code == 302 and "/auth/forgot" in r.headers["Location"]
    assert login(client, "admin@example.ly", "NewPass123").status_code == 302


def test_open_redirect_blocked(client, users):
    r = client.post("/auth/login?next=https://evil.example/", data={"identifier": "0921000001", "password": "Passw0rd1"})
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]


def test_csrf_enforced_when_enabled(app, users):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    r = c.post("/auth/login", data={"identifier": "0921000001", "password": "Passw0rd1"})
    assert r.status_code == 400
    r = c.post("/api/v1/notifications/read", json={})
    assert r.status_code in (400, 401)
