"""Input normalisation / validation helpers."""
import re

from flask_babel import lazy_gettext as _l
from wtforms.validators import ValidationError

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def to_latin_digits(s: str | None) -> str:
    return (s or "").translate(_ARABIC_DIGITS)


def normalize_phone(raw: str | None) -> str | None:
    """Normalise Libyan mobile numbers to 09XXXXXXXX; other numbers keep digits with leading +."""
    if not raw:
        return None
    s = re.sub(r"[\s\-().]", "", to_latin_digits(raw).strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+218"):
        s = "0" + s[4:]
    elif s.startswith("218") and len(s) == 12:
        s = "0" + s[3:]
    elif re.fullmatch(r"9[1-5]\d{7}", s):
        s = "0" + s
    if re.fullmatch(r"09[1-5]\d{7}", s):
        return s
    if re.fullmatch(r"\+?\d{7,15}", s):
        return s
    return None


def looks_like_email(s: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s or ""))


class Phone:
    def __init__(self, message=None):
        self.message = message or _l("Enter a valid phone number, e.g. 091-2345678.")

    def __call__(self, form, field):
        if field.data and normalize_phone(field.data) is None:
            raise ValidationError(self.message)


class StrongPassword:
    def __call__(self, form, field):
        pw = field.data or ""
        if len(pw) < 8 or not re.search(r"[A-Za-z؀-ۿ]", pw) or not re.search(r"\d", pw):
            raise ValidationError(_l("Password must be at least 8 characters and contain letters and numbers."))
