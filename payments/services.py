"""Transaction-safe payment state transitions, billing, and notifications."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import log_activity
from reservations.models import Reservation, ReservationStatus

from .models import BillingRecord, Payment, PaymentStatus


class PaymentTransitionError(ValidationError):
    """Raised when an attempted payment transition would lose financial state."""


def get_or_create_payment(reservation):
    """Return the reservation's single payment row, creating legacy gaps safely."""
    payment, _ = Payment.objects.get_or_create(
        reservation=reservation,
        defaults={
            "amount_cents": reservation.fee_cents,
            "reference": reservation.code,
        },
    )
    return payment


def prepare_payment(reservation, *, request=None):
    """Validate checkout eligibility and reset a failed payment for a new attempt."""
    with transaction.atomic():
        locked_reservation = Reservation.objects.select_for_update().get(
            pk=reservation.pk,
            customer=reservation.customer,
        )
        if locked_reservation.status != ReservationStatus.RESERVED:
            raise PaymentTransitionError(
                "Only an active reserved booking can be paid."
            )
        if locked_reservation.end_at <= timezone.now():
            raise PaymentTransitionError("This reservation's payment window has ended.")

        payment = get_or_create_payment(locked_reservation)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == PaymentStatus.FAILED:
            payment.status = PaymentStatus.PENDING
            payment.failure_notified_at = None
            # A confirmed failed attempt needs a new provider operation, while
            # repeated POSTs during the same pending attempt retain their key.
            # Clearing stale gateway IDs also prevents a webhook for the old
            # attempt from being mistaken for the newly opened checkout.
            payment.checkout_idempotency_key = uuid.uuid4()
            payment.checkout_session_id = ""
            payment.payment_intent_id = ""
            payment.save(
                update_fields=[
                    "status",
                    "failure_notified_at",
                    "checkout_idempotency_key",
                    "checkout_session_id",
                    "payment_intent_id",
                    "updated_at",
                ]
            )
            log_activity(
                "payment.retry_started",
                payment.reference,
                actor=locked_reservation.customer,
                request=request,
            )
        return payment


def _billing_defaults(payment, reservation):
    """Build the immutable receipt snapshot for one completed payment."""
    return {
        "customer": reservation.customer,
        "reservation": reservation,
        "amount_cents": payment.amount_cents,
        "description": (
            f"Parking reservation {reservation.code} — slot {reservation.slot.code}"
        ),
        "reference": reservation.code,
    }


def mark_paid(
    payment,
    *,
    method="",
    intent_id="",
    session_id="",
    when=None,
    actor=None,
    request=None,
):
    """Mark paid, repair/create its one receipt, and schedule one confirmation."""
    with transaction.atomic():
        # All financial writers lock the reservation before the payment.  A
        # consistent lock order avoids deadlocks with cancellation/check-in.
        payment_ref = Payment.objects.only("reservation_id").get(pk=payment.pk)
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("customer", "slot")
            .get(pk=payment_ref.reservation_id)
        )
        locked = Payment.objects.select_for_update().get(pk=payment.pk)

        locked.status = PaymentStatus.PAID
        locked.method = method or locked.method
        locked.payment_intent_id = intent_id or locked.payment_intent_id
        locked.checkout_session_id = session_id or locked.checkout_session_id
        locked.paid_at = locked.paid_at or when or timezone.now()

        should_notify = locked.confirmation_notified_at is None
        if should_notify:
            # Reserve the notification before commit so concurrent webhook
            # deliveries cannot each schedule the same email.
            locked.confirmation_notified_at = timezone.now()
        locked.save(
            update_fields=[
                "status",
                "method",
                "payment_intent_id",
                "checkout_session_id",
                "paid_at",
                "confirmation_notified_at",
                "updated_at",
            ]
        )

        BillingRecord.objects.get_or_create(
            payment=locked,
            defaults=_billing_defaults(locked, reservation),
        )
        action = (
            "payment.paid"
            if reservation.status != ReservationStatus.CANCELLED
            else "payment.paid_refund_review"
        )
        log_activity(
            action,
            f"{locked.reference} · {locked.amount_display}",
            # Gateway/simulator calls naturally attribute the event to the
            # customer, while manual reconciliation passes the administrator
            # explicitly so the financial audit trail names the real actor.
            actor=actor or reservation.customer,
            request=request,
        )
        if should_notify:
            transaction.on_commit(
                lambda: send_confirmation_email(reservation, locked)
            )
        return locked


def mark_failed(payment, *, actor=None, request=None):
    """Mark a non-paid attempt failed and notify the customer at most once."""
    with transaction.atomic():
        # Match every other financial writer's Reservation -> Payment lock
        # order so webhook, admin, checkout, and lifecycle transactions cannot
        # form a circular wait on MySQL.
        payment_ref = Payment.objects.only("reservation_id").get(pk=payment.pk)
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("customer", "slot")
            .get(pk=payment_ref.reservation_id)
        )
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        # Reuse the already-loaded relation for logging and the post-commit
        # notification instead of issuing an unlocked follow-up query.
        locked.reservation = reservation
        if locked.status == PaymentStatus.PAID:
            return locked

        was_failed = locked.status == PaymentStatus.FAILED
        should_notify = locked.failure_notified_at is None
        locked.status = PaymentStatus.FAILED
        if should_notify:
            locked.failure_notified_at = timezone.now()
        locked.save(
            update_fields=["status", "failure_notified_at", "updated_at"]
        )
        if not was_failed:
            log_activity(
                "payment.failed",
                locked.reference,
                actor=actor or reservation.customer,
                request=request,
            )
        if should_notify:
            transaction.on_commit(lambda: send_payment_failed_email(locked))
        return locked


def mark_pending(payment, *, actor=None, request=None):
    """Reopen a failed payment without ever downgrading a completed payment."""
    with transaction.atomic():
        payment_ref = Payment.objects.only("reservation_id").get(pk=payment.pk)
        Reservation.objects.select_for_update().get(pk=payment_ref.reservation_id)
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.status == PaymentStatus.PAID:
            raise PaymentTransitionError("A paid transaction cannot be reopened.")
        locked.status = PaymentStatus.PENDING
        locked.failure_notified_at = None
        locked.save(update_fields=["status", "failure_notified_at", "updated_at"])
        log_activity(
            "payment.set_pending",
            locked.reference,
            actor=actor,
            request=request,
        )
        return locked


def send_confirmation_email(reservation, payment):
    """Email the customer a combined booking and payment confirmation."""
    if not reservation.customer.email:
        return
    context = {
        "reservation": reservation,
        "payment": payment,
        "site_name": settings.SITE_NAME,
        "base_url": settings.SITE_BASE_URL,
    }
    send_mail(
        f"Booking confirmed — {reservation.code}",
        render_to_string("payments/email/confirmation.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer.email],
        fail_silently=True,
    )


def send_payment_failed_email(payment):
    """Give an asynchronously-failed customer a direct retry path."""
    reservation = payment.reservation
    if not reservation.customer.email:
        return
    context = {
        "reservation": reservation,
        "payment": payment,
        "site_name": settings.SITE_NAME,
        "base_url": settings.SITE_BASE_URL,
    }
    send_mail(
        f"Payment failed — {reservation.code}",
        render_to_string("payments/email/payment_failed.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer.email],
        fail_silently=True,
    )
