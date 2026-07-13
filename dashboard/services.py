"""Read-only aggregations powering the admin dashboard and reports.

Every function returns plain dicts/lists (no side effects) built with ORM
aggregates, so views stay thin and the numbers are easy to unit-test.
"""

from django.db.models import Count, Sum
from django.utils import timezone

from core.models import ActivityLog
from parking.models import Floor, Slot, SlotStatus
from payments.models import Payment, PaymentStatus
from reservations.models import ACTIVE_STATUSES, Reservation, ReservationStatus


def _counts_by(model, field, choices):
    """Return {choice_value: count} for ``field``, zero-filled for all choices."""
    raw = dict(model.objects.values_list(field).annotate(c=Count("id")))
    return {value: raw.get(value, 0) for value, _ in choices}


def slot_stats():
    """Return live slot KPIs without double-counting reservation rows.

    A slot is blocking only while an active reservation overlaps the current
    instant.  Physical maintenance takes precedence, so a maintenance slot is
    reported once in that category even if stale reservation data also covers
    it.
    """
    now = timezone.now()
    total = Slot.objects.count()
    maintenance = Slot.objects.filter(status=SlotStatus.MAINTENANCE).count()
    # Count distinct slot IDs because data imported from older deployments may
    # contain overlapping active rows for one slot; KPIs describe spaces, not
    # reservation records.
    blocking_now = (
        Reservation.objects.filter(
            status__in=ACTIVE_STATUSES,
            start_at__lte=now,
            end_at__gt=now,
        )
        .exclude(slot__status=SlotStatus.MAINTENANCE)
        .values("slot_id")
        .distinct()
        .count()
    )
    return {
        "total": total,
        "maintenance": maintenance,
        "occupied_now": blocking_now,
        # Maintenance and live reservation blockers are disjoint by design,
        # which keeps the availability equation stable even with stale data.
        "available_now": max(total - maintenance - blocking_now, 0),
    }


def reservation_stats():
    return _counts_by(Reservation, "status", ReservationStatus.choices)


def payment_stats():
    by_status = _counts_by(Payment, "status", PaymentStatus.choices)
    revenue_cents = (
        Payment.objects.filter(status=PaymentStatus.PAID).aggregate(
            s=Sum("amount_cents")
        )["s"]
        or 0
    )
    return {"by_status": by_status, "revenue_cents": revenue_cents}


def floor_breakdown():
    """Per-floor slot totals + maintenance counts for the reports table."""
    rows = []
    for floor in Floor.objects.all():
        slots = floor.slots.all()
        total = slots.count()
        maint = slots.filter(status=SlotStatus.MAINTENANCE).count()
        rows.append(
            {
                "floor": floor,
                "total": total,
                "maintenance": maint,
                "usable": total - maint,
            }
        )
    return rows


def monitor_slots(floor=None, vehicle_type=None):
    """All slots with a live ``monitor_status`` for the admin monitor.

    Status precedence per slot: maintenance (physical) > occupied (verified
    arrival covering now) > reserved (booked window covering now) > available.
    """
    now = timezone.now()
    qs = Slot.objects.select_related("floor")
    if floor:
        qs = qs.filter(floor=floor)
    if vehicle_type:
        qs = qs.filter(slot_type=vehicle_type)

    # Map slot_id -> current reservation status, preferring OCCUPIED.
    current = {}
    active = Reservation.objects.filter(
        status__in=ACTIVE_STATUSES, start_at__lte=now, end_at__gt=now
    ).values_list("slot_id", "status")
    for slot_id, status in active:
        if current.get(slot_id) != ReservationStatus.OCCUPIED:
            current[slot_id] = status

    slots = []
    for slot in qs:
        if slot.status == SlotStatus.MAINTENANCE:
            slot.monitor_status = "maintenance"
        elif current.get(slot.id) == ReservationStatus.OCCUPIED:
            slot.monitor_status = "occupied"
        elif slot.id in current:
            slot.monitor_status = "reserved"
        else:
            slot.monitor_status = "available"
        slots.append(slot)
    return slots


def recent_activity(limit=15):
    return ActivityLog.objects.select_related("actor")[:limit]


def dashboard_overview():
    """Everything the dashboard home + reports need, in one call."""
    payments = payment_stats()
    return {
        "slots": slot_stats(),
        "reservations": reservation_stats(),
        "payments": payments,
        "revenue_display": f"₱{payments['revenue_cents'] / 100:,.2f}",
        "floors": floor_breakdown(),
        "activity": recent_activity(),
    }
