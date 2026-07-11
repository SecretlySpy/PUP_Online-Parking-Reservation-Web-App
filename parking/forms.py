from django import forms

from core.constants import VehicleType

from .models import Floor, Slot


class SlotFilterForm(forms.Form):
    """Customer-facing filters for the real-time slot view."""

    floor = forms.ModelChoiceField(
        queryset=Floor.objects.filter(is_active=True),
        required=False,
        empty_label="All floors",
    )
    vehicle_type = forms.ChoiceField(
        choices=[("", "All types")] + list(VehicleType.choices), required=False
    )
    availability = forms.ChoiceField(
        choices=[("", "All slots"), ("available", "Available only")],
        required=False,
    )
    date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    start_time = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    end_time = forms.TimeField(
        required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-input").strip()


class FloorForm(forms.ModelForm):
    class Meta:
        model = Floor
        fields = ("name", "code", "sort_order", "is_active")


class SlotForm(forms.ModelForm):
    class Meta:
        model = Slot
        fields = ("floor", "code", "slot_type", "status")

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
