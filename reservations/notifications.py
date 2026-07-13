"""Customer email notifications for reservation lifecycle events."""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


def _send_reservation_email(*, reservation, subject, template_name, context=None):
    """Render and send one best-effort reservation email."""
    if not reservation.customer.email:
        return
    payload = {
        "reservation": reservation,
        "site_name": settings.SITE_NAME,
        "base_url": settings.SITE_BASE_URL,
        **(context or {}),
    }
    send_mail(
        subject,
        render_to_string(template_name, payload),
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer.email],
        # Notification delivery is operationally important but must never undo
        # an already-committed booking or cancellation.
        fail_silently=True,
    )


def send_reservation_created_email(reservation):
    """Tell the customer that a temporary hold was created and needs payment."""
    _send_reservation_email(
        reservation=reservation,
        subject=f"Reservation received — {reservation.code}",
        template_name="reservations/email/created.txt",
    )


def send_cancellation_email(reservation, *, cancelled_by):
    """Send a durable cancellation notice, including paid-booking guidance."""
    payment = getattr(reservation, "payment", None)
    _send_reservation_email(
        reservation=reservation,
        subject=f"Reservation cancelled — {reservation.code}",
        template_name="reservations/email/cancelled.txt",
        context={
            "cancelled_by": cancelled_by,
            "payment": payment,
            "requires_refund_review": bool(payment and payment.is_paid),
        },
    )
