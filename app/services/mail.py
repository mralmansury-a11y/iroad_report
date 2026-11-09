"""SMTP mailer connected to the agency mail server (Postfix / PostfixAdmin — mail.iroad.ly).

Supported modes (configured only through environment variables):
  * Authenticated submission (recommended):  MAIL_SERVER=mail.iroad.ly  MAIL_PORT=587  MAIL_USE_TLS=true
  * Implicit TLS (SMTPS):                    MAIL_PORT=465  MAIL_USE_SSL=true
  * Local Postfix relay, no auth:            MAIL_SERVER=localhost  MAIL_PORT=25  MAIL_USE_TLS=false

Every message is sent as text + HTML (bilingual-aware: the caller renders it in the
recipient's language) with proper Date / Message-ID headers for good deliverability.
When MAIL_SERVER is empty nothing is sent and a warning is logged.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from flask import current_app, render_template

log = logging.getLogger(__name__)


def mail_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def _tls_context(cfg) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not cfg.get("MAIL_VERIFY_TLS", True):  # only for an internal relay with a self-signed certificate
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def build_message(to: str, subject: str, body: str, html: str | None = None, reply_to: str | None = None) -> EmailMessage:
    cfg = current_app.config
    msg = EmailMessage()
    sender = cfg["MAIL_FROM"]
    msg["From"] = formataddr((cfg.get("MAIL_FROM_NAME") or "", sender)) if cfg.get("MAIL_FROM_NAME") else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg["Auto-Submitted"] = "auto-generated"  # RFC 3834: no auto-replies to system mail
    if reply_to or cfg.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = reply_to or cfg["MAIL_REPLY_TO"]
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send_mail(to: str, subject: str, body: str, html: str | None = None, reply_to: str | None = None) -> bool:
    """Send one message. Returns True on success; never raises (errors are logged)."""
    cfg = current_app.config
    if not mail_configured():
        log.warning("MAIL_SERVER not configured; e-mail to %s not sent (subject=%r)", to, subject)
        if current_app.debug or current_app.testing:
            log.warning("E-mail body (dev only):\n%s", body)
        return False
    msg = build_message(to, subject, body, html, reply_to)
    host, port, timeout = cfg["MAIL_SERVER"], int(cfg["MAIL_PORT"]), int(cfg.get("MAIL_TIMEOUT", 20))
    try:
        if cfg.get("MAIL_USE_SSL"):
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=_tls_context(cfg))
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server as s:
            s.ehlo()
            if cfg.get("MAIL_USE_TLS") and not cfg.get("MAIL_USE_SSL"):
                s.starttls(context=_tls_context(cfg))  # certificate + hostname verified
                s.ehlo()
            if cfg.get("MAIL_USERNAME"):
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            s.send_message(msg)
        log.info("e-mail sent to %s (subject=%r)", to, subject)
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("SMTP authentication failed for %s — check MAIL_USERNAME / MAIL_PASSWORD (PostfixAdmin mailbox)",
                  cfg.get("MAIL_USERNAME"))
    except smtplib.SMTPSenderRefused as exc:
        log.error("Sender refused (%s). With PostfixAdmin MAIL_FROM must be the authenticated mailbox or an alias it "
                  "owns (smtpd_sender_login_maps).", exc.smtp_error)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        log.error("SMTP send to %s failed: %s", to, exc)
    return False


def send_template(to: str, subject: str, template: str, reply_to: str | None = None, **ctx) -> bool:
    """Render `emails/<template>.txt` and `.html` (in the CURRENT locale) and send them."""
    from flask import url_for
    ctx.setdefault("subject", subject)
    ctx.setdefault("logo_url", url_for("static", filename="images/brand/irs-emblem.png", _external=True))
    body = render_template(f"emails/{template}.txt", **ctx)
    try:
        html = render_template(f"emails/{template}.html", **ctx)
    except Exception:  # html part is optional
        html = None
    return send_mail(to, subject, body, html, reply_to)
