"""Automated, idempotent reservation lifecycle transitions.

The public service in this module is intentionally independent of HTTP views so
it can be called safely by a scheduler, an operations script, or a future task
queue worker.  Every write includes the expected source status in its ``WHERE``
clause; that guard prevents a stale worker from overwriting a concurrent manual
change made by a customer or administrator.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import log_activity
from payments.models import Payment, PaymentStatus

from .models import Reservation, ReservationStatus
from .notifications import send_cancellation_email, send_reservation_reminder_email


# A sentinel lets callers explicitly pass ``None`` to disable expiry while the
# normal call path still reads the deployment's configured grace period.
_USE_CONFIGURED_GRACE = object()


@dataclass(frozen=True)
class LifecycleSummary:
    """Counts returned by one lifecycle-processing pass."""

    completed: int = 0
    ended_cancelled: int = 0
    unpaid_cancelled: int = 0
    reminders_sent: int = 0

    @property
    def total(self):
        """Return the number of reservations changed (or matched in dry-run).

        Reminders are a notification side effect, not a state change, so they
        are tracked separately and excluded from this transition total.
        """

        return self.completed + self.ended_cancelled + self.unpaid_cancelled


def _configured_payment_grace():
    """Return the opt-in unpaid hold grace as a ``timedelta`` or ``None``.

    Missing, zero, and ``None`` values deliberately disable unpaid expiry.  A
    conservative default matters during rollout because old reservations may
    have payment rows even though customers were never told about a deadline.
    """

    minutes = getattr(settings, "RESERVATION_PAYMENT_GRACE_MINUTES", None)
    if minutes in (None, "", 0, "0"):
        return None

    try:
        grace = timedelta(minutes=float(minutes))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "RESERVATION_PAYMENT_GRACE_MINUTES must be a positive number or empty."
        ) from exc

    if grace <= timedelta(0):
        raise ValueError("RESERVATION_PAYMENT_GRACE_MINUTES must be positive.")
    return grace


def _configured_reminder_window():
    """Return the pre-arrival reminder lead time as a ``timedelta`` or ``None``.

    Missing, zero, and ``None`` disable reminders — matching the conservative
    opt-in behaviour of the unpaid-hold grace period.
    """

    minutes = getattr(settings, "RESERVATION_REMINDER_MINUTES", None)
    if minutes in (None, "", 0, "0"):
        return None
    try:
        window = timedelta(minutes=float(minutes))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "RESERVATION_REMINDER_MINUTES must be a positive number or empty."
        ) from exc
    if window <= timedelta(0):
        raise ValueError("RESERVATION_REMINDER_MINUTES must be positive.")
    return window


def _send_due_reminders(*, at, window, dry_run):
    """Email a one-time reminder for paid reservations starting within window."""

    if window is None:
        return 0

    horizon = at + window
    candidates = Reservation.objects.filter(
        status=ReservationStatus.RESERVED,
        reminder_sent_at__isnull=True,
        start_at__gt=at,
        start_at__lte=horizon,
        payment__status=PaymentStatus.PAID,
    ).values_list("pk", "code")
    if dry_run:
        return candidates.count()

    changed = 0
    for reservation_id, code in candidates.iterator():
        with transaction.atomic():
            # Stamp-before-send under a conditional UPDATE guarantees at-most-once
            # delivery even if two workers race on the same reservation.
            updated = Reservation.objects.filter(
                pk=reservation_id,
                reminder_sent_at__isnull=True,
                status=ReservationStatus.RESERVED,
            ).update(reminder_sent_at=at)
            if not updated:
                continue
            reservation = Reservation.objects.select_related(
                "customer", "slot__floor"
            ).get(pk=reservation_id)
            log_activity(
                "reservation.reminder_sent",
                description=f"Sent an upcoming-arrival reminder for {code}.",
                target_user=reservation.customer,
            )
            transaction.on_commit(
                lambda r=reservation: send_reservation_reminder_email(r)
            )
            changed += 1
    return changed


def _normalise_at(at):
    """Return an aware processing timestamp and reject ambiguous naive input."""

    moment = at or timezone.now()
    if timezone.is_naive(moment):
        raise ValueError("Lifecycle processing requires a timezone-aware timestamp.")
    return moment


def _transition_ended(*, at, source_status, target_status, action, dry_run):
    """Transition ended rows without overwriting a concurrent status change."""

    candidates = Reservation.objects.filter(status=source_status, end_at__lte=at)
    if dry_run:
        # Counting without writing keeps dry-run free of status and audit changes.
        return candidates.count()

    changed = 0
    # Iterating identifiers keeps memory bounded even when a delayed scheduler
    # has accumulated a large backlog of historical reservations.
    for reservation_id, code in candidates.values_list("pk", "code").iterator():
        with transaction.atomic():
            # Repeating both lifecycle predicates in the UPDATE closes the race
            # between selecting candidates and applying the state transition.
            updated = Reservation.objects.filter(
                pk=reservation_id,
                status=source_status,
                end_at__lte=at,
            ).update(status=target_status, updated_at=at)
            if not updated:
                continue

            # Separate actions make CANCELLED-by-end distinguishable from an
            # unpaid hold expiry even though both share the same model status.
            log_activity(
                action,
                description=(
                    f"Reservation {code} changed from {source_status} to "
                    f"{target_status} automatically at {at.isoformat()}."
                ),
            )
            if target_status == ReservationStatus.CANCELLED:
                cancelled = Reservation.objects.select_related(
                    "customer", "slot__floor"
                ).get(pk=reservation_id)
                transaction.on_commit(
                    lambda reservation=cancelled: send_cancellation_email(
                        reservation,
                        cancelled_by="the automated lifecycle processor",
                    )
                )
            changed += 1
    return changed


def _expire_unpaid_holds(*, at, grace, dry_run):
    """Cancel future reserved holds whose existing payment remains non-paid."""

    if grace is None:
        return 0

    deadline = at - grace
    candidates = (
        Reservation.objects.filter(
            status=ReservationStatus.RESERVED,
            # Limiting this rule to reservations that have not started avoids
            # retroactively cancelling a booking while a vehicle may be onsite.
            start_at__gt=at,
            created_at__lte=deadline,
            payment__isnull=False,
        )
        .exclude(payment__status=PaymentStatus.PAID)
        .values_list("pk", "code")
    )
    if dry_run:
        return candidates.count()

    changed = 0
    for reservation_id, code in candidates.iterator():
        with transaction.atomic():
            # Financial writers lock Reservation then Payment.  Matching that
            # order avoids a deadlock while preventing payment completion from
            # interleaving with the expiry decision.
            reservation = (
                Reservation.objects.select_for_update()
                .select_related("customer", "slot__floor")
                .filter(
                    pk=reservation_id,
                    status=ReservationStatus.RESERVED,
                    start_at__gt=at,
                    created_at__lte=deadline,
                )
                .first()
            )
            if reservation is None:
                continue
            payment = (
                Payment.objects.select_for_update()
                .filter(reservation_id=reservation_id)
                .exclude(status=PaymentStatus.PAID)
                .first()
            )
            if payment is None:
                continue

            reservation.status = ReservationStatus.CANCELLED
            reservation.updated_at = at
            reservation.save(update_fields=["status", "updated_at"])

            log_activity(
                "reservation.unpaid_hold_expired",
                description=(
                    f"Reservation {code} was cancelled automatically because "
                    f"payment {payment.pk} remained {payment.status} beyond the "
                    f"{grace.total_seconds() / 60:g}-minute grace period."
                ),
                target_user=reservation.customer,
            )
            transaction.on_commit(
                lambda reservation=reservation: send_cancellation_email(
                    reservation,
                    cancelled_by="the automated payment-deadline processor",
                )
            )
            changed += 1
    return changed


def process_reservation_lifecycle(
    *, at=None, dry_run=False, payment_grace=_USE_CONFIGURED_GRACE
):
    """Apply all due lifecycle transitions and return a summary.

    Transition order is deliberate: ended ``OCCUPIED`` reservations complete,
    then ended ``RESERVED`` reservations cancel, and only future reservations
    are considered for unpaid-hold expiry.  The sets therefore cannot overlap,
    including during a dry run.

    Args:
        at: A timezone-aware effective timestamp; defaults to ``timezone.now``.
        dry_run: Count matching rows without changing state or writing activity.
        payment_grace: A ``timedelta`` override, ``None`` to disable unpaid
            expiry, or omitted to use ``RESERVATION_PAYMENT_GRACE_MINUTES``.
    """

    moment = _normalise_at(at)
    grace = (
        _configured_payment_grace()
        if payment_grace is _USE_CONFIGURED_GRACE
        else payment_grace
    )
    if grace is not None and (not isinstance(grace, timedelta) or grace <= timedelta(0)):
        raise ValueError("payment_grace must be a positive timedelta or None.")

    completed = _transition_ended(
        at=moment,
        source_status=ReservationStatus.OCCUPIED,
        target_status=ReservationStatus.COMPLETED,
        action="reservation.auto_completed",
        dry_run=dry_run,
    )
    ended_cancelled = _transition_ended(
        at=moment,
        source_status=ReservationStatus.RESERVED,
        target_status=ReservationStatus.CANCELLED,
        action="reservation.ended_unoccupied",
        dry_run=dry_run,
    )
    unpaid_cancelled = _expire_unpaid_holds(
        at=moment,
        grace=grace,
        dry_run=dry_run,
    )
    reminders_sent = _send_due_reminders(
        at=moment,
        window=_configured_reminder_window(),
        dry_run=dry_run,
    )

    return LifecycleSummary(
        completed=completed,
        ended_cancelled=ended_cancelled,
        unpaid_cancelled=unpaid_cancelled,
        reminders_sent=reminders_sent,
    )
