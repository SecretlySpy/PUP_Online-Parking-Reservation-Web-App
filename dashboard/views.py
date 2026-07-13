from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.models import CUSTOMER_ROLES, Roles
from core.constants import VehicleType
from core.models import log_activity
from parking.models import Floor
from payments.models import BillingRecord, Payment, PaymentStatus
from payments.services import (
    PaymentTransitionError,
    mark_failed,
    mark_paid,
    mark_pending,
)
from reservations.models import Reservation, ReservationStatus
from reservations.services import (
    ALLOWED_TRANSITIONS,
    ReservationTransitionError,
    transition_reservation,
)

from . import services

User = get_user_model()


def _page_context(request, queryset, page_parameter, page_size):
    """Paginate a queryset and retain every unrelated filter/page parameter.

    Separate page parameter names allow two tables to paginate independently
    on the same dashboard page without resetting the user's filters.
    """
    page = Paginator(queryset, page_size).get_page(request.GET.get(page_parameter))
    retained = request.GET.copy()
    retained.pop(page_parameter, None)
    return page, retained.urlencode()


def _customer_queryset():
    """Limit customer administration to non-privileged parking accounts."""
    # Role alone is insufficient: a legacy account can have a customer role
    # while still carrying Django staff/superuser privileges.
    return User.objects.filter(
        role__in=CUSTOMER_ROLES,
        is_staff=False,
        is_superuser=False,
    )


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
    reservations, pagination_query = _page_context(
        request, qs, "page", page_size=50
    )
    # The UI exposes only state-graph edges that the transactional service will
    # accept.  Server-side enforcement remains authoritative for crafted POSTs.
    for reservation in reservations.object_list:
        allowed = ALLOWED_TRANSITIONS.get(reservation.status, set())
        reservation.allowed_transitions = [
            (value, label)
            for value, label in ReservationStatus.choices
            if value in allowed
        ]
    return render(
        request,
        "dashboard/reservations.html",
        {
            "reservations": reservations,
            "pagination_query": pagination_query,
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
    new_status = request.POST.get("status")
    if new_status in {s for s, _ in ReservationStatus.choices}:
        try:
            reservation = transition_reservation(
                reservation_id=pk,
                new_status=new_status,
                actor=request.user,
                request=request,
            )
        except Reservation.DoesNotExist:
            get_object_or_404(Reservation, pk=pk)
        except ReservationTransitionError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(
                request,
                f"{reservation.code} set to {reservation.get_status_display()}.",
            )
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
    payment_page, payment_query = _page_context(
        request, payments, "payment_page", page_size=50
    )
    record_page, record_query = _page_context(
        request,
        BillingRecord.objects.select_related("customer"),
        "record_page",
        page_size=50,
    )
    return render(
        request,
        "dashboard/billing.html",
        {
            "payments": payment_page,
            "payment_query": payment_query,
            "statuses": PaymentStatus.choices,
            "current_status": status,
            "records": record_page,
            "record_query": record_query,
        },
    )


@admin_required
@require_POST
def payment_update_status(request, pk):
    """Apply a controlled manual reconciliation without downgrading paid rows."""
    payment = get_object_or_404(Payment, pk=pk)
    new_status = request.POST.get("status")
    try:
        if new_status == payment.status:
            messages.info(request, "That payment already has the requested status.")
        elif payment.is_paid:
            raise PaymentTransitionError(
                "A paid transaction is immutable; use the manual refund workflow."
            )
        elif new_status == PaymentStatus.PAID:
            payment = mark_paid(
                payment,
                method="manual-admin",
                actor=request.user,
                request=request,
            )
            messages.success(request, f"{payment.reference} reconciled as paid.")
        elif new_status == PaymentStatus.FAILED:
            payment = mark_failed(
                payment,
                actor=request.user,
                request=request,
            )
            messages.success(request, f"{payment.reference} marked failed.")
        elif new_status == PaymentStatus.PENDING:
            payment = mark_pending(payment, actor=request.user, request=request)
            messages.success(request, f"{payment.reference} reopened as pending.")
        else:
            messages.error(request, "Invalid payment status.")
    except PaymentTransitionError as exc:
        messages.error(request, exc.messages[0])
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:billing")


# --- Customer administration -----------------------------------------------

@admin_required
def customers(request):
    """Search and filter customer accounts without exposing administrators."""
    queryset = (
        _customer_queryset()
        .annotate(
            reservation_count=Count("reservations", distinct=True),
            vehicle_count=Count("vehicles", distinct=True),
        )
        # Aggregation removes the model's implicit ordering on some databases;
        # an explicit stable tiebreaker prevents records moving between pages.
        .order_by("-date_joined", "-pk")
    )
    query = (request.GET.get("q") or "").strip()
    role = request.GET.get("role") or ""
    active = request.GET.get("active") or ""

    if query:
        # Match operational identifiers as well as names so staff can locate a
        # customer from either a profile, school ID, or contact detail.
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(id_number__icontains=query)
            | Q(contact_number__icontains=query)
        )
    if role in CUSTOMER_ROLES:
        queryset = queryset.filter(role=role)
    if active in {"1", "0"}:
        queryset = queryset.filter(is_active=(active == "1"))

    customer_page, pagination_query = _page_context(
        request, queryset, "page", page_size=50
    )
    return render(
        request,
        "dashboard/customers.html",
        {
            "customers": customer_page,
            "customer_roles": [
                (value, label)
                for value, label in Roles.choices
                if value in CUSTOMER_ROLES
            ],
            "current_query": query,
            "current_role": role,
            "current_active": active,
            "pagination_query": pagination_query,
        },
    )


@admin_required
def customer_detail(request, pk):
    """Show one customer's profile and complete parking/payment history."""
    customer = get_object_or_404(_customer_queryset(), pk=pk)
    reservations = customer.reservations.select_related(
        "slot", "slot__floor", "vehicle"
    )
    payments = Payment.objects.filter(reservation__customer=customer).select_related(
        "reservation"
    )

    # Independent paginators keep both histories bounded while allowing staff
    # to inspect a deep page in one table without moving the other table.
    reservation_page, reservation_query = _page_context(
        request, reservations, "reservation_page", page_size=20
    )
    payment_page, payment_query = _page_context(
        request, payments, "payment_page", page_size=20
    )
    payment_counts = dict(
        # Clear chronological ordering before grouping so SQL backends do not
        # accidentally split one status into multiple timestamp groups.
        payments.order_by()
        .values("status")
        .annotate(total=Count("id"))
        .values_list("status", "total")
    )
    paid_total = (
        payments.filter(status=PaymentStatus.PAID).aggregate(
            total=Sum("amount_cents")
        )["total"]
        or 0
    )
    return render(
        request,
        "dashboard/customer_detail.html",
        {
            "customer_account": customer,
            "vehicles": customer.vehicles.all(),
            "reservations": reservation_page,
            "reservation_query": reservation_query,
            "payments": payment_page,
            "payment_query": payment_query,
            "payment_counts": {
                value: payment_counts.get(value, 0) for value, _ in PaymentStatus.choices
            },
            "paid_total_display": f"₱{paid_total / 100:,.2f}",
        },
    )


@admin_required
@require_POST
def customer_toggle_active(request, pk):
    """Activate/deactivate a customer while protecting privileged accounts."""
    requested_state = request.POST.get("is_active")
    if requested_state not in {None, "0", "1"}:
        messages.error(request, "Invalid account status.")
        return redirect("dashboard:customers")

    with transaction.atomic():
        # Locking prevents two simultaneous admin actions from racing when the
        # compatibility toggle mode (no explicit state) is used.
        target = get_object_or_404(User.objects.select_for_update(), pk=pk)
        if target.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("dashboard:customers")
        if target.is_admin_role or not target.is_customer_role:
            messages.error(request, "Administrator accounts cannot be changed here.")
            return redirect("dashboard:customers")

        new_state = (
            not target.is_active
            if requested_state is None
            else requested_state == "1"
        )
        if target.is_active != new_state:
            target.is_active = new_state
            target.save(update_fields=["is_active"])
            action = "customer.activated" if new_state else "customer.deactivated"
            log_activity(
                action,
                f"{target.username} ({target.get_role_display()})",
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                f"{target.username} has been {'activated' if new_state else 'deactivated'}.",
            )
        else:
            messages.info(request, f"{target.username} already has that account status.")

    return redirect("dashboard:customer_detail", pk=target.pk)


# --- Reports ----------------------------------------------------------------

@admin_required
def reports(request):
    return render(request, "dashboard/reports.html", services.dashboard_overview())
