from django.conf import settings
from django.db import models
from django.utils import timezone

from parking.models import Slot

from .utils import make_reservation_code, sign_reservation


class ReservationStatus(models.TextChoices):
    RESERVED = "RESERVED", "Reserved"        # booked, not yet arrived
    OCCUPIED = "OCCUPIED", "Occupied"        # verified on arrival, in use
    COMPLETED = "COMPLETED", "Completed"     # session finished
    CANCELLED = "CANCELLED", "Cancelled"     # cancelled by user/admin


#: Statuses that hold a slot and therefore block overlapping bookings.
ACTIVE_STATUSES = (ReservationStatus.RESERVED, ReservationStatus.OCCUPIED)


class Reservation(models.Model):
    """A booking of one slot for a [start_at, end_at) window by a customer."""

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reservations"
    )
    # PROTECT: a slot with reservations cannot be silently deleted.
    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, related_name="reservations")
    # SET_NULL: keep the historical booking even if the vehicle is removed.
    vehicle = models.ForeignKey(
        "accounts.Vehicle", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reservations",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=ReservationStatus.choices,
        default=ReservationStatus.RESERVED,
    )
    code = models.CharField(max_length=16, unique=True, editable=False)
    # Fee snapshot (centavos) taken at booking time; paid in Phase 4.
    fee_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["slot", "status", "start_at", "end_at"])]

    def __str__(self):
        return f"{self.code} · {self.slot.code}"

    def save(self, *args, **kwargs):
        # Assign a unique code on first save; retry on the rare collision.
        if not self.code:
            for _ in range(5):
                candidate = make_reservation_code()
                if not Reservation.objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
        if not self.fee_cents:
            self.fee_cents = settings.RESERVATION_FEE_CENTS
        super().save(*args, **kwargs)

    # --- Derived state ---
    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES

    @property
    def is_cancellable(self):
        return self.status == ReservationStatus.RESERVED and self.start_at > timezone.now()

    @property
    def is_modifiable(self):
        return self.is_cancellable

    @property
    def fee_display(self):
        return f"₱{self.fee_cents / 100:.2f}"

    @property
    def qr_token(self):
        return sign_reservation(self)

    @property
    def status_badge(self):
        return self.status.lower()

    @staticmethod
    def overlapping(slot, start, end, exclude_pk=None):
        """Active reservations on ``slot`` overlapping [start, end)."""
        qs = Reservation.objects.filter(
            slot=slot, status__in=ACTIVE_STATUSES,
            start_at__lt=end, end_at__gt=start,
        )
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs
