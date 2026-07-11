from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, customer_required
from core.models import log_activity
from parking.models import Slot

from .forms import ReservationForm
from .models import Reservation, ReservationStatus
from .utils import qr_png_bytes, unsign_token, verification_url


def _owner_or_admin(request, reservation):
    """True if the requester owns the reservation or is an administrator."""
    return reservation.customer_id == request.user.id or request.user.is_admin_role


# --- Booking -----------------------------------------------------------------

@customer_required
def create(request, slot_id):
    slot = get_object_or_404(Slot, pk=slot_id)
    # Carry any date/time chosen on the slot-search page into the booking form.
    initial = {
        "date": request.GET.get("date"),
        "start_time": request.GET.get("start_time"),
        "end_time": request.GET.get("end_time"),
    }
    if request.method == "POST":
        form = ReservationForm(request.POST, slot=slot, user=request.user)
        if form.is_valid():
            reservation = Reservation.objects.create(
                customer=request.user,
                slot=slot,
                vehicle=form.cleaned_data["vehicle"],
                start_at=form.cleaned_data["start_at"],
                end_at=form.cleaned_data["end_at"],
            )
            log_activity(
                "reservation.created",
                f"{reservation.code} · {slot.code}",
                actor=request.user,
                request=request,
            )
            messages.success(request, f"Slot {slot.code} reserved — code {reservation.code}.")
            return redirect("reservations:detail", pk=reservation.pk)
    else:
        form = ReservationForm(initial=initial, slot=slot, user=request.user)

    if not request.user.vehicles.exists():
        messages.info(request, "Add a vehicle first, then book your slot.")
    return render(request, "reservations/create.html", {"form": form, "slot": slot})


# --- Read --------------------------------------------------------------------

def detail(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk)
    if not (request.user.is_authenticated and _owner_or_admin(request, reservation)):
        raise PermissionDenied
    # Reverse OneToOne to the payment; None until a payment is started. Caught
    # broadly so we don't import the payments app into reservations.
    try:
        payment = reservation.payment
    except ObjectDoesNotExist:
        payment = None
    return render(
        request,
        "reservations/detail.html",
        {"reservation": reservation, "payment": payment},
    )


@customer_required
def history(request):
    reservations = request.user.reservations.select_related("slot", "slot__floor")
    return render(request, "reservations/history.html", {"reservations": reservations})


# --- Modify / cancel ---------------------------------------------------------

@customer_required
def modify(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk, customer=request.user)
    if not reservation.is_modifiable:
        messages.error(request, "This reservation can no longer be modified.")
        return redirect("reservations:detail", pk=pk)
    if request.method == "POST":
        form = ReservationForm(
            request.POST, slot=reservation.slot, user=request.user, exclude_pk=pk
        )
        if form.is_valid():
            reservation.vehicle = form.cleaned_data["vehicle"]
            reservation.start_at = form.cleaned_data["start_at"]
            reservation.end_at = form.cleaned_data["end_at"]
            reservation.save()
            log_activity("reservation.modified", reservation.code, actor=request.user, request=request)
            messages.success(request, "Reservation updated.")
            return redirect("reservations:detail", pk=pk)
    else:
        form = ReservationForm(
            initial={
                "vehicle": reservation.vehicle_id,
                "date": reservation.start_at.date(),
                "start_time": reservation.start_at.time(),
                "end_time": reservation.end_at.time(),
            },
            slot=reservation.slot,
            user=request.user,
            exclude_pk=pk,
        )
    return render(
        request,
        "reservations/create.html",
        {"form": form, "slot": reservation.slot, "editing": reservation},
    )


@customer_required
@require_POST
def cancel(request, pk):
    reservation = get_object_or_404(Reservation, pk=pk, customer=request.user)
    if not reservation.is_cancellable:
        messages.error(request, "This reservation can no longer be cancelled.")
        return redirect("reservations:detail", pk=pk)
    reservation.status = ReservationStatus.CANCELLED
    reservation.save(update_fields=["status", "updated_at"])
    log_activity("reservation.cancelled", reservation.code, actor=request.user, request=request)
    messages.success(request, "Reservation cancelled.")
    return redirect("reservations:history")


# --- QR + arrival verification ----------------------------------------------

def qr(request, pk):
    """Return the reservation's QR code as a PNG (owner or staff only)."""
    reservation = get_object_or_404(Reservation, pk=pk)
    if not (request.user.is_authenticated and _owner_or_admin(request, reservation)):
        raise PermissionDenied
    png = qr_png_bytes(verification_url(reservation))
    return HttpResponse(png, content_type="image/png")


@admin_required
def verify(request):
    """Staff scan/enter a token on arrival; validate and mark OCCUPIED."""
    token = request.GET.get("t") or request.POST.get("t")
    payload = unsign_token(token) if token else None
    reservation = None
    if payload:
        reservation = (
            Reservation.objects.filter(pk=payload.get("id"), code=payload.get("code"))
            .select_related("slot", "customer")
            .first()
        )

    if request.method == "POST" and reservation:
        if reservation.status == ReservationStatus.RESERVED:
            reservation.status = ReservationStatus.OCCUPIED
            reservation.save(update_fields=["status", "updated_at"])
            log_activity(
                "reservation.verified",
                f"{reservation.code} marked occupied",
                actor=request.user,
                request=request,
            )
            messages.success(request, f"{reservation.code} verified — slot now occupied.")
        else:
            messages.info(request, f"{reservation.code} is {reservation.get_status_display()}.")
        return redirect(f"{request.path}?t={token}")

    return render(
        request,
        "reservations/verify.html",
        {"reservation": reservation, "token": token, "invalid": token and not reservation},
    )
