from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, customer_required
from core.models import log_activity
from parking.models import Slot

from .forms import ReservationForm
from .models import Reservation, ReservationStatus
from .services import (
    ReservationConflict,
    ReservationTransitionError,
    check_in_error,
    create_reservation,
    modify_reservation,
    payment_for,
    transition_reservation,
)
from .utils import qr_png_bytes, unsign_token, verification_url


def _owner_or_admin(request, reservation):
    """True if the requester owns the reservation or is an administrator."""
    return reservation.customer_id == request.user.id or request.user.is_admin_role


# --- Booking -----------------------------------------------------------------

@customer_required
def create(request, slot_id):
    # Booking is gated on a verified email; self-registered customers start
    # unverified until they follow the emailed link.
    if not getattr(request.user, "email_verified", True):
        messages.info(request, "Please verify your email before booking a slot.")
        return redirect("accounts:verify_notice")
    slot = get_object_or_404(Slot, pk=slot_id)
    # Carry any date/time/vehicle chosen on the slot-search page or a "Rebook"
    # link into the booking form (quick re-book).
    initial = {
        "date": request.GET.get("date"),
        "start_time": request.GET.get("start_time"),
        "end_time": request.GET.get("end_time"),
        "vehicle": request.GET.get("vehicle"),
    }
    if request.method == "POST":
        form = ReservationForm(request.POST, slot=slot, user=request.user)
        if form.is_valid():
            try:
                reservation = create_reservation(
                    customer=request.user,
                    slot_id=slot.pk,
                    vehicle_id=form.cleaned_data["vehicle"].pk,
                    start_at=form.cleaned_data["start_at"],
                    end_at=form.cleaned_data["end_at"],
                    request=request,
                )
            except (ReservationConflict, ValidationError) as exc:
                # A concurrent request may win after form validation; surface
                # the authoritative transaction result as a normal form error.
                form.add_error(None, exc.messages[0])
            else:
                messages.success(
                    request,
                    f"Slot {slot.code} reserved — code {reservation.code}.",
                )
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
    page = Paginator(reservations, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "reservations/history.html",
        {"reservations": page.object_list, "page_obj": page},
    )


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
            try:
                modify_reservation(
                    reservation_id=reservation.pk,
                    customer=request.user,
                    vehicle_id=form.cleaned_data["vehicle"].pk,
                    start_at=form.cleaned_data["start_at"],
                    end_at=form.cleaned_data["end_at"],
                    request=request,
                )
            except (ReservationConflict, ReservationTransitionError, ValidationError) as exc:
                form.add_error(None, exc.messages[0])
            else:
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
    try:
        transition_reservation(
            reservation_id=reservation.pk,
            new_status=ReservationStatus.CANCELLED,
            actor=request.user,
            request=request,
            customer_cancel=True,
        )
    except ReservationTransitionError as exc:
        messages.error(request, exc.messages[0])
        return redirect("reservations:detail", pk=pk)
    messages.success(
        request,
        "Reservation cancelled. Paid bookings require manual refund review.",
    )
    return redirect("reservations:history")


# --- QR + arrival verification ----------------------------------------------

def qr(request, pk):
    """Return the reservation's QR code as a PNG (owner or staff only)."""
    reservation = get_object_or_404(
        Reservation.objects.select_related("customer"),
        pk=pk,
    )
    if not (request.user.is_authenticated and _owner_or_admin(request, reservation)):
        raise PermissionDenied
    payment = payment_for(reservation)
    if not reservation.is_active or not payment or not payment.is_paid:
        # The template gate is only presentation.  This endpoint must enforce
        # payment itself because its predictable URL can be requested directly.
        raise PermissionDenied
    png = qr_png_bytes(verification_url(reservation))
    response = HttpResponse(png, content_type="image/png")
    if request.GET.get("download"):
        response["Content-Disposition"] = (
            f'attachment; filename="reservation-{reservation.code}.png"'
        )
    return response


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

    eligibility_error = check_in_error(reservation) if reservation else ""
    if request.method == "POST" and reservation:
        try:
            reservation = transition_reservation(
                reservation_id=reservation.pk,
                new_status=ReservationStatus.OCCUPIED,
                actor=request.user,
                request=request,
            )
        except ReservationTransitionError as exc:
            messages.error(request, exc.messages[0])
        else:
            log_activity(
                "reservation.verified",
                f"{reservation.code} marked occupied",
                actor=request.user,
                request=request,
                target_user=reservation.customer,
            )
            messages.success(
                request,
                f"{reservation.code} verified — slot now occupied.",
            )
        return redirect(f"{request.path}?t={token}")

    return render(
        request,
        "reservations/verify.html",
        {
            "reservation": reservation,
            "token": token,
            "invalid": token and not reservation,
            "eligibility_error": eligibility_error,
        },
    )
