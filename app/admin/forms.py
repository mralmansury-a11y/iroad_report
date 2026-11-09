from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateTimeLocalField, DecimalField, EmailField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from ..utils.validators import Phone, StrongPassword


class StatusForm(FlaskForm):
    to_status = SelectField(_l("New status"), validators=[DataRequired()])
    public_note = TextAreaField(_l("Note to the reporter (visible)"), validators=[Optional(), Length(max=1000)])
    internal_note = TextAreaField(_l("Internal note (staff only)"), validators=[Optional(), Length(max=2000)])


class AssignForm(FlaskForm):
    team_id = SelectField(_l("Team"), coerce=int, validators=[Optional()])
    assignee_id = SelectField(_l("Employee"), coerce=int, validators=[Optional()])
    note = TextAreaField(_l("Instructions"), validators=[Optional(), Length(max=1000)])


class NoteForm(FlaskForm):
    body = TextAreaField(_l("Note"), validators=[DataRequired(), Length(max=5000)])
    visibility = SelectField(_l("Visibility"), choices=[("internal", _l("Internal (staff only)")),
                                                        ("public", _l("Official response (visible to reporter)"))])


class UserForm(FlaskForm):
    full_name = StringField(_l("Full name"), validators=[DataRequired(), Length(min=3, max=120)])
    phone = StringField(_l("Phone number"), validators=[Optional(), Phone()])
    email = EmailField(_l("E-mail"), validators=[Optional(), Length(max=255)])
    job_title = StringField(_l("Job title"), validators=[Optional(), Length(max=120)])
    locale = SelectField(_l("Language"), choices=[("ar", "العربية"), ("en", "English")])
    roles = SelectMultipleField(_l("Roles"), coerce=int)
    teams = SelectMultipleField(_l("Teams"), coerce=int)
    password = PasswordField(_l("Password"), validators=[Optional(), StrongPassword()])
    active = BooleanField(_l("Active account"), default=True)


class TranslatedNameForm(FlaskForm):
    code = StringField(_l("Code"), validators=[DataRequired(), Length(max=32)])
    name_ar = StringField(_l("Name (Arabic)"), validators=[DataRequired(), Length(max=120)])
    name_en = StringField(_l("Name (English)"), validators=[DataRequired(), Length(max=120)])
    is_active = BooleanField(_l("Active"), default=True)


class TeamForm(TranslatedNameForm):
    description_ar = TextAreaField(_l("Description (Arabic)"), validators=[Optional(), Length(max=500)])
    description_en = TextAreaField(_l("Description (English)"), validators=[Optional(), Length(max=500)])


class CategoryForm(TranslatedNameForm):
    icon = StringField(_l("Icon (Bootstrap Icons class)"), validators=[DataRequired(), Length(max=48)],
                       default="bi-exclamation-triangle")
    sort_order = IntegerField(_l("Order"), default=0, validators=[Optional()])
    default_team_id = SelectField(_l("Default team"), coerce=int, validators=[Optional()])


class SectionForm(TranslatedNameForm):
    km_start = DecimalField(_l("From km"), places=2, validators=[DataRequired(), NumberRange(min=0)])
    km_end = DecimalField(_l("To km"), places=2, validators=[DataRequired(), NumberRange(min=0)])
    sort_order = IntegerField(_l("Order"), default=0, validators=[Optional()])
    road_status = SelectField(_l("Road status"), choices=[("open", _l("Road open")), ("partial", _l("Partially open")),
                                                          ("closed", _l("Road closed"))])
    visibility_pct = IntegerField(_l("Visibility rate (%)"), validators=[Optional(), NumberRange(min=0, max=100)])


class RoadPointsForm(FlaskForm):
    csv = TextAreaField(_l("Reference points (km,latitude,longitude — one per line)"),
                        validators=[DataRequired(), Length(max=200000)])
    replace = BooleanField(_l("Replace all existing points"))


class AnnouncementForm(FlaskForm):
    kind = SelectField(_l("Type"), choices=[
        ("weather", _l("Weather alert")), ("traffic", _l("Expected congestion")), ("project", _l("Project update")),
        ("closure", _l("Road closure")), ("emergency", _l("Emergency")), ("general", _l("Announcement"))])
    title_ar = StringField(_l("Title (Arabic)"), validators=[DataRequired(), Length(max=200)])
    title_en = StringField(_l("Title (English)"), validators=[DataRequired(), Length(max=200)])
    body_ar = TextAreaField(_l("Text (Arabic)"), validators=[Optional(), Length(max=3000)])
    body_en = TextAreaField(_l("Text (English)"), validators=[Optional(), Length(max=3000)])
    km_from = DecimalField(_l("From km"), places=1, validators=[Optional(), NumberRange(min=0)])
    km_to = DecimalField(_l("To km"), places=1, validators=[Optional(), NumberRange(min=0)])
    road_section_id = SelectField(_l("Road section"), coerce=int, validators=[Optional()])
    starts_at = DateTimeLocalField(_l("Starts"), format="%Y-%m-%dT%H:%M", validators=[Optional()])
    ends_at = DateTimeLocalField(_l("Ends"), format="%Y-%m-%dT%H:%M", validators=[Optional()])
    is_published = BooleanField(_l("Publish now"))
    send_notification = BooleanField(_l("Send a notification to users"))


class MessageForm(FlaskForm):
    status = SelectField(_l("Status"), choices=[("new", _l("New")), ("answered", _l("Answered")), ("closed", _l("Closed"))])
    reply = TextAreaField(_l("Reply / handling note"), validators=[Optional(), Length(max=3000)])
