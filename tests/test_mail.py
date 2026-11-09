"""E-mail integration (SMTP is mocked — no real mail server needed)."""
import smtplib

import pytest

from app.extensions import db
from app.models import ContactMessage

from .conftest import login


class FakeSMTP:
    sent, calls = [], []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls", context is not None))

    def login(self, user, pw):
        FakeSMTP.calls.append(("login", user))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def smtp(app, monkeypatch):
    FakeSMTP.sent, FakeSMTP.calls = [], []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    app.config.update(MAIL_SERVER="mail.iroad.ly", MAIL_PORT=587, MAIL_USE_TLS=True, MAIL_USE_SSL=False,
                      MAIL_USERNAME="no-reply@iroad.ly", MAIL_PASSWORD="x", MAIL_FROM="no-reply@iroad.ly",
                      MAIL_FROM_NAME="الطريق الدولي ليبيا", MAIL_REPLY_TO="support@iroad.ly")
    return FakeSMTP


def _text(msg):
    return msg.get_body(("plain",)).get_content()


def test_password_reset_mail(client, users, smtp):
    r = client.post("/auth/forgot", data={"email": "admin@example.ly"})
    assert r.status_code == 302
    assert ("connect", "mail.iroad.ly", 587) in smtp.calls and ("starttls", True) in smtp.calls
    assert ("login", "no-reply@iroad.ly") in smtp.calls
    msg = smtp.sent[0]
    assert msg["To"] == "admin@example.ly" and "no-reply@iroad.ly" in msg["From"]
    assert msg["Subject"].startswith("إعادة تعيين كلمة المرور")  # account language (ar)
    assert msg["Message-ID"] and msg["Date"] and msg["Reply-To"] == "support@iroad.ly"
    assert "/auth/reset/" in _text(msg)
    html = msg.get_body(("html",)).get_content()
    assert 'dir="rtl"' in html and "/auth/reset/" in html


def test_reset_mail_in_english_for_english_account(client, users, smtp):
    users["admin"].locale = "en"
    db.session.commit()
    client.post("/auth/forgot", data={"email": "admin@example.ly"})
    assert smtp.sent[0]["Subject"].startswith("Password reset")


def test_unknown_email_sends_nothing(client, users, smtp):
    r = client.post("/auth/forgot", data={"email": "nobody@example.ly"})
    assert r.status_code == 302 and smtp.sent == []


def test_password_changed_notice(client, users, smtp, app):
    from app.auth.routes import make_reset_token
    with app.test_request_context():
        tok = make_reset_token(users["admin"])
    client.post(f"/auth/reset/{tok}", data={"password": "NewPass123", "confirm": "NewPass123"})
    assert any("تغيير كلمة المرور" in m["Subject"] for m in smtp.sent)


def test_support_reply_by_email(client, users, smtp):
    m = ContactMessage(name="زائر", contact="visitor@example.com", body="سؤال")
    db.session.add(m)
    db.session.commit()
    login(client, "0921000003")
    client.post(f"/admin/messages/{m.id}", data={"status": "answered", "reply": "تمت المعالجة"})
    msg = smtp.sent[-1]
    assert msg["To"] == "visitor@example.com" and "تمت المعالجة" in _text(msg)


def test_mail_disabled_does_not_crash(client, users, app):
    app.config["MAIL_SERVER"] = ""
    assert client.post("/auth/forgot", data={"email": "admin@example.ly"}).status_code == 302


def test_smtp_failure_is_handled(client, users, smtp, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(smtplib, "SMTP", boom)
    assert client.post("/auth/forgot", data={"email": "admin@example.ly"}).status_code == 302


def test_cli_send_test_mail(app, smtp):
    out = app.test_cli_runner().invoke(args=["send-test-mail", "it@iroad.ly"])
    assert "Test message sent" in out.output and smtp.sent[0]["To"] == "it@iroad.ly"
