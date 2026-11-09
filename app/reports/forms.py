from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from wtforms import DecimalField, HiddenField, RadioField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from ..utils.validators import Phone

SEVERITY_CHOICES = [("low", _l("Minor")), ("medium", _l("Moderate")), ("high", _l("Serious"))]


class ReportForm(FlaskForm):
    category_id = RadioField(_l("Problem type"), coerce=int, validators=[DataRequired(message=_l("Choose the problem type."))])
    title = StringField(_l("Short title (optional)"), validators=[Optional(), Length(max=160)])
    # The location is set ONLY with "Use my location" (GPS) or "Pick on map".
    # Kilometre marker and road section are calculated on the server from the coordinates.
    latitude = DecimalField(validators=[Optional(), NumberRange(min=-90, max=90)], places=6)
    longitude = DecimalField(validators=[Optional(), NumberRange(min=-180, max=180)], places=6)
    location_source = HiddenField(default="manual")
    severity = RadioField(_l("Severity"), choices=SEVERITY_CHOICES, default="medium", validators=[DataRequired()])
    images = MultipleFileField(_l("Photo (optional)"))
    description = TextAreaField(_l("Description"), validators=[Optional(), Length(max=3000)])
    guest_name = StringField(_l("Your name"), validators=[Optional(), Length(max=120)])
    guest_phone = StringField(_l("Phone number (to follow up your report)"), validators=[Optional(), Phone()])

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if self.latitude.data is None or self.longitude.data is None:
            self.latitude.errors = list(self.latitude.errors) + [
                _l("Set the location with “Use my location” or “Pick on map”.")]
            ok = False
        if self.location_source.data not in ("gps", "map"):
            self.location_source.data = "map"
        return ok


class TrackForm(FlaskForm):
    reference = StringField(_l("Report reference number"), validators=[DataRequired(), Length(max=24)])
    phone = StringField(_l("Phone number used in the report"), validators=[DataRequired(), Phone()])
