from django.conf import settings
from django.db import models


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class Payment(models.Model):
    """A reservation-fee payment processed through the gateway (PayMongo).

    One payment per reservation (OneToOne); retries reuse the same row and just
    create a fresh checkout session. ``method`` is filled from the gateway once
    the customer picks GCash / Maya / card.
    """

    reservation = models.OneToOneField(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="payment"
    )
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=8, default="PHP")
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    method = models.CharField(max_length=32, blank=True)  # gcash/paymaya/card
    provider = models.CharField(max_length=32, default="paymongo")
    # Gateway identifiers used to reconcile webhooks with this row.
    checkout_session_id = models.CharField(max_length=128, blank=True)
    payment_intent_id = models.CharField(max_length=128, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference or self.pk} · {self.get_status_display()}"

    @property
    def amount_display(self):
        return f"₱{self.amount_cents / 100:.2f}"

    @property
    def is_paid(self):
        return self.status == PaymentStatus.PAID


class BillingRecord(models.Model):
    """A receipt/billing line issued when a payment is completed."""

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="billing_records"
    )
    reservation = models.ForeignKey(
        "reservations.Reservation", on_delete=models.SET_NULL, null=True,
        related_name="billing_records",
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, related_name="billing_records"
    )
    amount_cents = models.PositiveIntegerField()
    description = models.CharField(max_length=255)
    reference = models.CharField(max_length=64, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"{self.reference} · {self.amount_display}"

    @property
    def amount_display(self):
        return f"₱{self.amount_cents / 100:.2f}"
