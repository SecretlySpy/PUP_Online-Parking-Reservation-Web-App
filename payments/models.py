import uuid

from django.conf import settings
from django.db import models


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class Payment(models.Model):
    """A reservation-fee payment processed through the gateway (PayMongo).

    One payment per reservation (OneToOne); repeated requests for one pending
    attempt reuse its idempotent hosted checkout, while a confirmed failed
    attempt rotates to a new key. ``method`` is filled from the gateway once
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
    # The same key is reused throughout one pending attempt so PayMongo can
    # collapse browser retries/concurrent clicks; a confirmed failure rotates
    # it before a new attempt starts.
    checkout_idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )
    payment_intent_id = models.CharField(max_length=128, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # These timestamps make notification scheduling idempotent across duplicate
    # webhook deliveries.  They describe an attempted dispatch, not guaranteed
    # delivery; production SMTP monitoring remains responsible for delivery.
    confirmation_notified_at = models.DateTimeField(null=True, blank=True)
    failure_notified_at = models.DateTimeField(null=True, blank=True)
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


class WebhookOutcome(models.TextChoices):
    """Terminal processing result retained for each verified delivery."""

    PROCESSED = "PROCESSED", "Processed"
    IGNORED = "IGNORED", "Ignored"
    REJECTED = "REJECTED", "Rejected"


class PayMongoWebhookEvent(models.Model):
    """Durable idempotency and audit record for one PayMongo event.

    PayMongo may retry a delivery after a lost response. The provider event ID
    is unique, so persisting it in the same transaction as the payment change
    prevents duplicate financial side effects across workers and processes.
    """

    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=64)
    livemode = models.BooleanField()
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_events",
    )
    outcome = models.CharField(
        max_length=16,
        choices=WebhookOutcome.choices,
        default=WebhookOutcome.IGNORED,
    )
    detail = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_id} · {self.outcome}"


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
        constraints = [
            # A completed gateway payment has one canonical receipt line.  The
            # database constraint is the final backstop against webhook races.
            models.UniqueConstraint(
                fields=["payment"],
                name="unique_billing_record_per_payment",
            )
        ]

    def __str__(self):
        return f"{self.reference} · {self.amount_display}"

    @property
    def amount_display(self):
        return f"₱{self.amount_cents / 100:.2f}"
