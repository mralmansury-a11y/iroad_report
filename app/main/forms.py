from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional

from ..utils.validators import Phone, StrongPassword


class ProfileForm(FlaskForm):
    full_name = StringField(_l("Full name"), validators=[DataRequired(), Length(min=3, max=120)])
    phone = StringField(_l("Phone number"), validators=[Optional(), Phone()])
    email = EmailField(_l("E-mail (optional)"), validators=[Optional(), Length(max=255)])
    home_section_id = SelectField(_l("Region / section"), coerce=int, validators=[Optional()])


class PasswordForm(FlaskForm):
    current = PasswordField(_l("Current password"), validators=[DataRequired()])
    password = PasswordField(_l("New password"), validators=[DataRequired(), StrongPassword()])
    confirm = PasswordField(_l("Confirm password"),
                            validators=[DataRequired(), EqualTo("password", message=_l("Passwords do not match."))])


class NotificationPrefsForm(FlaskForm):
    report_updates = BooleanField(_l("Updates on my reports"))
    weather_alerts = BooleanField(_l("Weather alerts"))
    project_updates = BooleanField(_l("Project updates"))
    points_rewards = BooleanField(_l("Points and rewards"))
    sound = BooleanField(_l("Sound notifications"))
    push_enabled = BooleanField(_l("Push notifications on my devices"))


class ContactForm(FlaskForm):
    name = StringField(_l("Name"), validators=[DataRequired(), Length(max=120)])
    contact = StringField(_l("Phone or e-mail"), validators=[DataRequired(), Length(max=255)])
    body = TextAreaField(_l("Message"), validators=[DataRequired(), Length(min=5, max=3000)])
