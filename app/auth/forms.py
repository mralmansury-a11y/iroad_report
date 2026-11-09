from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, ValidationError

from ..utils.validators import Phone, StrongPassword, looks_like_email, normalize_phone


class LoginForm(FlaskForm):
    identifier = StringField(_l("Phone number or e-mail"), validators=[DataRequired(), Length(max=255)])
    password = PasswordField(_l("Password"), validators=[DataRequired(), Length(max=128)])
    remember = BooleanField(_l("Remember me"))


class RegisterForm(FlaskForm):
    full_name = StringField(_l("Full name"), validators=[DataRequired(), Length(min=3, max=120)])
    phone = StringField(_l("Phone number"), validators=[Optional(), Phone()])
    email = EmailField(_l("E-mail (optional)"), validators=[Optional(), Length(max=255)])
    password = PasswordField(_l("Password"), validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(_l("Confirm password"),
                            validators=[DataRequired(), EqualTo("password", message=_l("Passwords do not match."))])
    accept = BooleanField(_l("I agree to the privacy policy"), validators=[DataRequired()])

    def validate_email(self, field):
        if field.data and not looks_like_email(field.data):
            raise ValidationError(_l("Enter a valid e-mail address."))

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if not (self.phone.data or self.email.data):
            self.phone.errors = list(self.phone.errors) + [_l("Enter a phone number or an e-mail address.")]
            return False
        return ok

    @property
    def normalized_phone(self):
        return normalize_phone(self.phone.data)


class ForgotForm(FlaskForm):
    email = EmailField(_l("E-mail"), validators=[DataRequired(), Length(max=255)])


class ResetForm(FlaskForm):
    password = PasswordField(_l("New password"), validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(_l("Confirm password"),
                            validators=[DataRequired(), EqualTo("password", message=_l("Passwords do not match."))])


class ChangePasswordForm(FlaskForm):
    current = PasswordField(_l("Current password"), validators=[DataRequired()])
    password = PasswordField(_l("New password"), validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(_l("Confirm password"),
                            validators=[DataRequired(), EqualTo("password", message=_l("Passwords do not match."))])
