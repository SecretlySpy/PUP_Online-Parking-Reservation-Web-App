"""Transactional reservation operations and lifecycle transition policy.

Views deliberately delegate writes to this module.  Keeping the authoritative
checks beside the transaction prevents a request from validating stale state
and then committing a conflicting reservation.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Vehicle
from core.models import log_activity
from parking.models import Slot
from payments.models import Payment, PaymentStatus

from .models import Reservation, ReservationStatus
from .notifications import send_cancellation_email, send_reservation_created_email


class ReservationConflict(ValidationError):
    """Raised when a requested slot window conflicts with an active booking."""


class ReservationTransitionError(ValidationError):
    """Raised when a reservation status change violates the lifecycle policy."""


# The state graph is intentionally one-way.  Reactivating a cancelled booking
# could silently overlap a replacement booking made after its cancellation.
ALLOWED_TRANSITIONS = {
    ReservationStatus.RESERVED: {
        ReservationStatus.OCCUPIED,
        ReservationStatus.CANCELLED,
    },
    ReservationStatus.OCCUPIED: {ReservationStatus.COMPLETED},
    ReservationStatus.COMPLETED: set(),
    ReservationStatus.CANCELLED: set(),
}


def _validate_booking_resources(*, slot, vehicle, customer):
    """Validate mutable inventory and ownership rules inside the write lock."""
    if not slot.floor.is_active:
        raise ValidationError("This parking floor is not accepting reservations.")
    if not slot.is_open:
        raise ValidationError("This slot is currently under maintenance.")
    if vehicle.owner_id != customer.pk:
        raise ValidationError("Select a vehicle that belongs to your account.")
    if not slot.accommodates(vehicle.vehicle_type):
        raise ValidationError("The selected vehicle type does not match this slot.")


def _lock_vehicle(*, vehicle_id, customer):
    """Load the submitted vehicle from the authenticated customer's inventory."""
    try:
        return Vehicle.objects.select_for_update().get(
            pk=vehicle_id,
            owner=customer,
        )
    except Vehicle.DoesNotExist as exc:
        raise ValidationError("The selected vehicle is unavailable.") from exc


def create_reservation(*, customer, slot_id, vehicle_id, start_at, end_at, request=None):
    """Create one conflict-free reservation and its pending payment atomically."""
    with transaction.atomic():
        # Locking the inventory row serializes all bookings for the same slot on
        # MySQL, the production database, making the following overlap check
        # authoritative rather than merely advisory form validation.
        try:
            slot = (
                Slot.objects.select_for_update()
                .select_related("floor")
                .get(pk=slot_id)
            )
        except Slot.DoesNotExist as exc:
            raise ValidationError("This parking slot is unavailable.") from exc

        vehicle = _lock_vehicle(vehicle_id=vehicle_id, customer=customer)
        _validate_booking_resources(slot=slot, vehicle=vehicle, customer=customer)

        if Reservation.overlapping(slot, start_at, end_at).exists():
            raise ReservationConflict(
                "That slot was just booked for an overlapping time. "
                "Pick another slot or time."
            )

        reservation = Reservation.objects.create(
            customer=customer,
            slot=slot,
            vehicle=vehicle,
            start_at=start_at,
            end_at=end_at,
        )

        # Every hold gets a payment row immediately.  Lifecycle processing can
        # therefore expire abandoned checkouts consistently, including users
        # who never click the payment button.
        Payment.objects.create(
            reservation=reservation,
            amount_cents=reservation.fee_cents,
            reference=reservation.code,
        )

        log_activity(
            "reservation.created",
            f"{reservation.code} · {slot.code}",
            actor=customer,
            request=request,
        )
        transaction.on_commit(lambda: send_reservation_created_email(reservation))
        return reservation


def modify_reservation(
    *,
    reservation_id,
    customer,
    vehicle_id,
    start_at,
    end_at,
    request=None,
):
    """Update a future reservation while holding its reservation and slot rows."""
    with transaction.atomic():
        try:
            reservation = (
                Reservation.objects.select_for_update()
                .select_related("slot__floor")
                .get(pk=reservation_id, customer=customer)
            )
        except Reservation.DoesNotExist as exc:
            raise ValidationError("This reservation is unavailable.") from exc

        if not reservation.is_modifiable:
            raise ReservationTransitionError(
                "This reservation can no longer be modified."
            )

        # Lock the resource independently of the reservation row so a create
        # and a modify targeting the same slot cannot pass the overlap check at
        # the same time.
        slot = (
            Slot.objects.select_for_update()
            .select_related("floor")
            .get(pk=reservation.slot_id)
        )
        vehicle = _lock_vehicle(vehicle_id=vehicle_id, customer=customer)
        _validate_booking_resources(slot=slot, vehicle=vehicle, customer=customer)

        if Reservation.overlapping(
            slot,
            start_at,
            end_at,
            exclude_pk=reservation.pk,
        ).exists():
            raise ReservationConflict(
                "That slot was just booked for an overlapping time. "
                "Pick another slot or time."
            )

        reservation.vehicle = vehicle
        reservation.start_at = start_at
        reservation.end_at = end_at
        reservation.save(
            update_fields=["vehicle", "start_at", "end_at", "updated_at"]
        )
        log_activity(
            "reservation.modified",
            reservation.code,
            actor=customer,
            request=request,
        )
        return reservation


def payment_for(reservation):
    """Return the related payment or ``None`` without leaking ORM exceptions."""
    try:
        return reservation.payment
    except ObjectDoesNotExist:
        return None


def check_in_error(reservation, *, at=None):
    """Return a literal reason check-in is disallowed, or an empty string."""
    at = at or timezone.now()
    payment = payment_for(reservation)
    if not payment or payment.status != PaymentStatus.PAID:
        return "Payment must be completed before arrival can be verified."
    if reservation.status != ReservationStatus.RESERVED:
        return "Only a reserved booking can be checked in."

    # A small configurable early-arrival window handles gate queues without
    # allowing a valid QR to occupy a slot hours or days before its booking.
    grace_minutes = getattr(settings, "RESERVATION_ARRIVAL_GRACE_MINUTES", 15)
    earliest = reservation.start_at - timedelta(minutes=max(grace_minutes, 0))
    if at < earliest:
        return "This reservation is not yet within its arrival window."
    if at >= reservation.end_at:
        return "This reservation's arrival window has ended."
    return ""


def transition_reservation(
    *,
    reservation_id,
    new_status,
    actor=None,
    request=None,
    customer_cancel=False,
    at=None,
):
    """Apply one allowed reservation transition under a row lock."""
    at = at or timezone.now()
    with transaction.atomic():
        reservation = (
            Reservation.objects.select_for_update()
            .select_related("customer", "slot")
            .get(pk=reservation_id)
        )
        old_status = reservation.status

        if new_status == old_status:
            return reservation
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ReservationTransitionError(
                f"{reservation.get_status_display()} cannot transition to "
                f"{ReservationStatus(new_status).label}."
            )
        if customer_cancel and (
            old_status != ReservationStatus.RESERVED or reservation.start_at <= at
        ):
            raise ReservationTransitionError(
                "This reservation can no longer be cancelled."
            )
        if new_status == ReservationStatus.OCCUPIED:
            reason = check_in_error(reservation, at=at)
            if reason:
                raise ReservationTransitionError(reason)

        reservation.status = new_status
        reservation.save(update_fields=["status", "updated_at"])
        log_activity(
            "reservation.status_set",
            f"{reservation.code}: {old_status}→{new_status}",
            actor=actor,
            request=request,
        )

        if new_status == ReservationStatus.CANCELLED:
            payment = payment_for(reservation)
            if payment and payment.is_paid:
                # Refund execution remains an operator/gateway procedure, but
                # this explicit audit event makes every paid cancellation a
                # discoverable reconciliation item instead of silent mismatch.
                log_activity(
                    "reservation.refund_review_required",
                    f"{reservation.code} · payment {payment.pk}",
                    actor=actor,
                    request=request,
                )
            cancelled_by = str(actor) if actor else "the system"
            transaction.on_commit(
                lambda: send_cancellation_email(
                    reservation,
                    cancelled_by=cancelled_by,
                )
            )
        return reservation
