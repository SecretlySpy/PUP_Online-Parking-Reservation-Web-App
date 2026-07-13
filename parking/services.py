"""Slot availability computation.

Availability has two layers:

* physical  — the slot must not be under maintenance (``Slot.is_open``);
* temporal  — for a requested [start, end) window the slot must have no
  overlapping active reservation.

The reservation layer is resolved lazily via ``apps.get_model`` to avoid a
module-level circular import while keeping availability window-aware.
"""

from datetime import datetime, timedelta

from django.apps import apps
from django.utils import timezone

from .models import Floor, Slot, SlotStatus

# Reservation statuses that make a slot unavailable for an overlapping window.
BLOCKING_RESERVATION_STATUSES = ("RESERVED", "OCCUPIED")

# A minimal window used to test "occupied right now" via the overlap query.
_INSTANT = timedelta(seconds=1)


def build_window(date=None, start_time=None, end_time=None):
    """Combine a date + start/end times into aware datetimes.

    Returns ``(start, end)`` or ``(None, None)`` if the window is incomplete,
    in which case only physical availability is considered.
    """
    if not (date and start_time and end_time):
        return None, None
    start = datetime.combine(date, start_time)
    end = datetime.combine(date, end_time)
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    if timezone.is_naive(end):
        end = timezone.make_aware(end)
    if end <= start:
        return None, None
    return start, end


def blocked_slot_ids(start, end):
    """Slot ids with an active reservation overlapping [start, end)."""
    if not (start and end):
        return set()
    try:
        Reservation = apps.get_model("reservations", "Reservation")
    except LookupError:
        return set()
    overlapping = Reservation.objects.filter(
        status__in=BLOCKING_RESERVATION_STATUSES,
        start_at__lt=end,
        end_at__gt=start,
    )
    return set(overlapping.values_list("slot_id", flat=True))


def query_slots(*, floor=None, vehicle_type=None):
    qs = Slot.objects.select_related("floor").filter(floor__is_active=True)
    if floor:
        qs = qs.filter(floor=floor)
    if vehicle_type:
        qs = qs.filter(slot_type=vehicle_type)
    return qs


def slots_with_availability(
    *, floor=None, vehicle_type=None, only_available=False, start=None, end=None
):
    """Return slots (each annotated with an ``available`` bool) plus a summary.

    ``available`` = open (not under maintenance) AND not reserved for the window.
    """
    slots = list(query_slots(floor=floor, vehicle_type=vehicle_type))
    blocked = blocked_slot_ids(start, end)
    for slot in slots:
        slot.available = slot.is_open and slot.id not in blocked
    if only_available:
        slots = [s for s in slots if s.available]
    summary = {
        "total": len(slots),
        "available": sum(1 for s in slots if s.available),
        "maintenance": sum(1 for s in slots if s.status == SlotStatus.MAINTENANCE),
    }
    return slots, summary


def active_floors():
    return Floor.objects.filter(is_active=True)


def facility_floors():
    """Per-floor summary for the public Facility Guide.

    Returns a list of ``{floor, total, available, occupied, maintenance}`` for
    each active floor, using the same live-occupancy logic as the availability
    engine (a slot is occupied now if an active reservation covers ``now``).
    """
    now = timezone.now()
    occupied_ids = blocked_slot_ids(now, now + _INSTANT)
    rows = []
    for floor in active_floors():
        slots = list(floor.slots.all())
        total = len(slots)
        maintenance = sum(1 for s in slots if s.status == SlotStatus.MAINTENANCE)
        occupied = sum(
            1
            for s in slots
            if s.id in occupied_ids and s.status != SlotStatus.MAINTENANCE
        )
        rows.append(
            {
                "floor": floor,
                "total": total,
                "available": max(total - maintenance - occupied, 0),
                "occupied": occupied,
                "maintenance": maintenance,
            }
        )
    return rows
