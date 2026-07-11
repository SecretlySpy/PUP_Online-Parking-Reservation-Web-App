from datetime import timedelta

from django import forms
from django.utils import timezone

from accounts.models import Vehicle
from parking.services import build_window

from .models import Reservation

# Guardrails on booking length.
MAX_DURATION = timedelta(hours=24)
MIN_DURATION = timedelta(minutes=15)


class ReservationForm(forms.Form):
    """Collects vehicle + date/time window for booking a specific slot.

    The slot is fixed (passed in), so this form validates the temporal window
    and guarantees no double-booking of that slot.
    """

    vehicle = forms.ModelChoiceField(queryset=None, required=True)
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))

    def __init__(self, *args, slot=None, user=None, exclude_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.slot = slot
        self.user = user
        self.exclude_pk = exclude_pk
        # Only the signed-in customer's own vehicles are selectable.
        self.fields["vehicle"].queryset = (
            user.vehicles.all() if user else Vehicle.objects.none()
        )
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-input").strip()

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("date")
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        if not (date and start_time and end_time):
            return cleaned

        start, end = build_window(date, start_time, end_time)
        if not start:
            raise forms.ValidationError("End time must be after start time.")

        # Reject bookings in the past and enforce sane duration bounds.
        if start <= timezone.now():
            raise forms.ValidationError("Start time must be in the future.")
        duration = end - start
        if duration < MIN_DURATION:
            raise forms.ValidationError("Reservation is too short (minimum 15 minutes).")
        if duration > MAX_DURATION:
            raise forms.ValidationError("Reservation is too long (maximum 24 hours).")

        # Slot must be physically open (not under maintenance).
        if self.slot and not self.slot.is_open:
            raise forms.ValidationError("This slot is currently under maintenance.")

        # No overlapping active reservation on the same slot.
        if self.slot and Reservation.overlapping(
            self.slot, start, end, exclude_pk=self.exclude_pk
        ).exists():
            raise forms.ValidationError(
                "That slot is already booked for an overlapping time. "
                "Pick another slot or time."
            )

        cleaned["start_at"] = start
        cleaned["end_at"] = end
        return cleaned
