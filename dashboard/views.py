from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from core.constants import VehicleType
from core.models import log_activity
from parking.models import Floor
from payments.models import BillingRecord, Payment, PaymentStatus
from reservations.models import Reservation, ReservationStatus

from . import services


@admin_required
def home(request):
    """Dashboard overview: KPIs + recent activity."""
    return render(request, "dashboard/home.html", services.dashboard_overview())


# --- Live slot monitor ------------------------------------------------------

def _monitor_filters(request):
    floor_id = request.GET.get("floor") or None
    vtype = request.GET.get("vehicle_type") or None
    floor = Floor.objects.filter(pk=floor_id).first() if floor_id else None
    return floor, vtype, floor_id


@admin_required
def monitor(request):
    floor, vtype, floor_id = _monitor_filters(request)
    return render(
        request,
        "dashboard/monitor.html",
        {
            "slots": services.monitor_slots(floor=floor, vehicle_type=vtype),
            "floors": Floor.objects.all(),
            "vehicle_types": VehicleType.choices,
            "current_floor": floor_id,
            "current_type": vtype,
        },
    )


@admin_required
def monitor_partial(request):
    """Polled fragment for the live monitor auto-refresh."""
    floor, vtype, _ = _monitor_filters(request)
    return render(
        request,
        "dashboard/_monitor_grid.html",
        {"slots": services.monitor_slots(floor=floor, vehicle_type=vtype)},
    )


# --- Reservation manager ----------------------------------------------------

@admin_required
def reservations_manager(request):
    qs = Reservation.objects.select_related("slot", "slot__floor", "customer")
    status = request.GET.get("status") or None
    floor_id = request.GET.get("floor") or None
    if status:
        qs = qs.filter(status=status)
    if floor_id:
        qs = qs.filter(slot__floor_id=floor_id)
    return render(
        request,
        "dashboard/reservations.html",
        {
            "reservations": qs[:200],
            "statuses": ReservationStatus.choices,
            "floors": Floor.objects.all(),
            "current_status": status,
            "current_floor": floor_id,
        },
    )


@admin_required
@require_POST
def reservation_update_status(request, pk):
    """Admin override of a reservation's status."""
    reservation = get_object_or_404(Reservation, pk=pk)
    new_status = request.POST.get("status")
    if new_status in {s for s, _ in ReservationStatus.choices}:
        old = reservation.status
        reservation.status = new_status
        reservation.save(update_fields=["status", "updated_at"])
        log_activity(
            "reservation.status_set",
            f"{reservation.code}: {old}→{new_status}",
            actor=request.user,
            request=request,
        )
        messages.success(request, f"{reservation.code} set to {reservation.get_status_display()}.")
    else:
        messages.error(request, "Invalid status.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:reservations")


# --- Billing / payments -----------------------------------------------------

@admin_required
def billing(request):
    payments = Payment.objects.select_related("reservation", "reservation__customer")
    status = request.GET.get("status") or None
    if status:
        payments = payments.filter(status=status)
    return render(
        request,
        "dashboard/billing.html",
        {
            "payments": payments[:200],
            "statuses": PaymentStatus.choices,
            "current_status": status,
            "records": BillingRecord.objects.select_related("customer")[:50],
        },
    )


# --- Reports ----------------------------------------------------------------

@admin_required
def reports(request):
    return render(request, "dashboard/reports.html", services.dashboard_overview())
