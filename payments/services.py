"""Payment lifecycle: create → mark paid/failed → issue billing + email.

All state transitions are idempotent so a webhook delivered more than once (a
normal gateway behaviour) does not double-charge, double-issue receipts, or
send duplicate emails.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import log_activity

from .models import BillingRecord, Payment, PaymentStatus


def get_or_create_payment(reservation):
    """Return the reservation's pending payment, creating it if missing."""
    payment, _ = Payment.objects.get_or_create(
        reservation=reservation,
        defaults={
            "amount_cents": reservation.fee_cents,
            "reference": reservation.code,
        },
    )
    return payment


def mark_paid(payment, *, method="", intent_id="", session_id="", when=None, request=None):
    """Transition a payment to PAID and run the completion side effects once."""
    if payment.status == PaymentStatus.PAID:
        return payment  # idempotent: already handled

    payment.status = PaymentStatus.PAID
    payment.method = method or payment.method
    payment.payment_intent_id = intent_id or payment.payment_intent_id
    payment.checkout_session_id = session_id or payment.checkout_session_id
    payment.paid_at = when or timezone.now()
    payment.save()

    # Issue a billing/receipt line (guard against duplicates on retries).
    reservation = payment.reservation
    if not payment.billing_records.exists():
        BillingRecord.objects.create(
            customer=reservation.customer,
            reservation=reservation,
            payment=payment,
            amount_cents=payment.amount_cents,
            description=f"Parking reservation {reservation.code} — slot {reservation.slot.code}",
            reference=reservation.code,
        )

    send_confirmation_email(reservation, payment)
    log_activity(
        "payment.paid",
        f"{payment.reference} · {payment.amount_display}",
        actor=reservation.customer,
        request=request,
    )
    return payment


def mark_failed(payment, *, request=None):
    """Transition a payment to FAILED (idempotent)."""
    if payment.status == PaymentStatus.PAID:
        return payment  # never downgrade a completed payment
    payment.status = PaymentStatus.FAILED
    payment.save(update_fields=["status", "updated_at"])
    log_activity(
        "payment.failed", payment.reference,
        actor=payment.reservation.customer, request=request,
    )
    return payment


def send_confirmation_email(reservation, payment):
    """Email the customer a booking + payment confirmation."""
    if not reservation.customer.email:
        return
    context = {
        "reservation": reservation,
        "payment": payment,
        "site_name": settings.SITE_NAME,
        "base_url": settings.SITE_BASE_URL,
    }
    subject = f"Booking confirmed — {reservation.code}"
    body = render_to_string("payments/email/confirmation.txt", context)
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer.email],
        fail_silently=True,  # email must never break the payment flow
    )
