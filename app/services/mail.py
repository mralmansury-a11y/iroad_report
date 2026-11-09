"""Minimal SMTP mailer (used for password reset). Logs instead of sending when SMTP is not configured."""
import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def send_mail(to: str, subject: str, body: str) -> bool:
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        log.warning("MAIL_SERVER not configured; e-mail to %s not sent (subject=%r)", to, subject)
        if current_app.debug or current_app.testing:
            log.warning("E-mail body (dev only):\n%s", body)
        return False
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as s:
            if cfg.get("MAIL_USE_TLS"):
                s.starttls()
            if cfg.get("MAIL_USERNAME"):
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover
        log.error("SMTP send failed: %s", exc)
        return False
