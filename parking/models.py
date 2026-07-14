from django.db import models
from django.utils import timezone

from core.constants import VehicleType


class SlotStatus(models.TextChoices):
    """Physical state of a slot, set by staff. Live occupancy is derived
    separately from overlapping reservations."""

    AVAILABLE = "AVAILABLE", "Available"
    MAINTENANCE = "MAINTENANCE", "Under maintenance"


class Floor(models.Model):
    """A level/area of the campus parking facility."""

    name = models.CharField(max_length=64)
    code = models.CharField(max_length=8, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Static-relative path to a representative photo (shown on the facility
    # guide + slot views), e.g. "img/areas/area-1.jpg". Optional.
    image = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Slot(models.Model):
    """An individual parking space belonging to a floor."""

    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name="slots")
    code = models.CharField(max_length=16)
    slot_type = models.CharField(
        max_length=16, choices=VehicleType.choices, default=VehicleType.CAR
    )
    status = models.CharField(
        max_length=16, choices=SlotStatus.choices, default=SlotStatus.AVAILABLE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["floor__sort_order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["floor", "code"], name="unique_slot_code_per_floor"
            )
        ]

    def __str__(self):
        return f"{self.code} ({self.floor.code})"

    @property
    def is_open(self):
        """True if the slot is not under maintenance (physical availability)."""
        return self.status == SlotStatus.AVAILABLE

    @property
    def status_badge(self):
        return "available" if self.is_open else "maintenance"

    def accommodates(self, vehicle_type):
        return self.slot_type == vehicle_type


class OccupancySnapshot(models.Model):
    """A point-in-time capture of facility occupancy + revenue for trend charts.

    Written periodically by the ``capture_occupancy_snapshot`` command so the
    reports page can plot history (all other dashboard stats are instantaneous).
    """

    captured_at = models.DateTimeField(default=timezone.now, db_index=True)
    total = models.PositiveIntegerField()
    available = models.PositiveIntegerField()
    occupied = models.PositiveIntegerField()
    maintenance = models.PositiveIntegerField()
    paid_revenue_cents = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.captured_at:%Y-%m-%d %H:%M} · {self.occupied}/{self.total} occupied"
