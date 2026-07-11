from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import CUSTOMER_ROLES, Roles, User, Vehicle

# Shared fields for the profile portion of registration / profile editing.
PROFILE_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "email",
    "id_number",
    "contact_number",
    "address",
)


def _style(fields):
    """Add a consistent CSS class to every widget for the PUP form styling."""
    for field in fields.values():
        css = field.widget.attrs.get("class", "")
        field.widget.attrs["class"] = (css + " form-input").strip()


class CustomerRegistrationForm(UserCreationForm):
    """Registration for students, employees, and visitors."""

    role = forms.ChoiceField(
        choices=[(r.value, r.label) for r in CUSTOMER_ROLES],
        initial=Roles.STUDENT.value,
    )

    class Meta:
        model = User
        fields = ("username", "role", *PROFILE_FIELDS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True
        _style(self.fields)

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role not in {r.value for r in CUSTOMER_ROLES}:
            raise forms.ValidationError("Invalid account type.")
        return role


class AdminRegistrationForm(UserCreationForm):
    """Separate administrator registration, gated by an access code."""

    access_code = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        help_text="Provided by the system owner.",
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True
        _style(self.fields)

    def clean_access_code(self):
        expected = getattr(settings, "ADMIN_SIGNUP_CODE", "")
        provided = self.cleaned_data.get("access_code", "")
        if expected and provided != expected:
            raise forms.ValidationError("Incorrect administrator access code.")
        return provided

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = Roles.ADMIN
        user.is_staff = True
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = PROFILE_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True
        _style(self.fields)


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ("plate_number", "vehicle_type", "make", "model", "color")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)

    def clean_plate_number(self):
        return self.cleaned_data["plate_number"].strip().upper()
