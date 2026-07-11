import json

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import customer_required
from reservations.models import Reservation

from . import gateway
from .models import Payment, PaymentStatus
from .services import get_or_create_payment, mark_failed, mark_paid


def _abs_url(path):
    """Build an absolute URL (gateway requires absolute success/cancel URLs)."""
    return f"{settings.SITE_BASE_URL}{path}"


@customer_required
def start(request, reservation_id):
    """Begin payment for a reservation: real gateway or dev simulation."""
    reservation = get_object_or_404(
        Reservation, pk=reservation_id, customer=request.user
    )
    payment = get_or_create_payment(reservation)
    if payment.is_paid:
        messages.info(request, "This reservation is already paid.")
        return redirect("reservations:detail", pk=reservation.pk)

    # Dev/no-keys mode: use the built-in simulated gateway page.
    if not gateway.is_configured():
        return redirect("payments:simulate", pk=payment.pk)

    # Real PayMongo hosted checkout.
    success = _abs_url(reverse("payments:return") + f"?pk={payment.pk}")
    cancel = _abs_url(reverse("reservations:detail", args=[reservation.pk]))
    try:
        session_id, checkout_url = gateway.create_checkout_session(
            payment, success, cancel
        )
    except gateway.PayMongoError:
        messages.error(request, "Could not reach the payment gateway. Try again.")
        return redirect("reservations:detail", pk=reservation.pk)
    payment.checkout_session_id = session_id
    payment.save(update_fields=["checkout_session_id", "updated_at"])
    return redirect(checkout_url)


@customer_required
def simulate(request, pk):
    """Dev-only simulated gateway (active when no PayMongo keys are set)."""
    if gateway.is_configured():
        raise PermissionDenied  # real gateway configured — no simulation
    payment = get_object_or_404(Payment, pk=pk, reservation__customer=request.user)
    if request.method == "POST":
        if request.POST.get("action") == "success":
            mark_paid(payment, method="simulated", request=request)
            messages.success(request, "Payment successful (simulated).")
            return redirect("payments:receipt", pk=payment.pk)
        mark_failed(payment, request=request)
        messages.error(request, "Payment failed (simulated).")
        return redirect("reservations:detail", pk=payment.reservation.pk)
    return render(request, "payments/simulate.html", {"payment": payment})


@customer_required
def gateway_return(request):
    """Landing after real checkout. Webhook is source of truth; show status."""
    payment = get_object_or_404(
        Payment, pk=request.GET.get("pk"), reservation__customer=request.user
    )
    if payment.is_paid:
        return redirect("payments:receipt", pk=payment.pk)
    messages.info(request, "We're confirming your payment. This page will update shortly.")
    return redirect("reservations:detail", pk=payment.reservation.pk)


@csrf_exempt
@require_POST
def webhook(request):
    """Receive PayMongo events and reconcile payment status (source of truth)."""
    if not gateway.verify_webhook_signature(request):
        return HttpResponse(status=401)
    try:
        event = json.loads(request.body.decode())
        attributes = event["data"]["attributes"]
        event_type = attributes["type"]
        resource = attributes.get("data", {})
    except (ValueError, KeyError):
        return HttpResponseBadRequest("bad payload")

    resource_id = resource.get("id", "")
    attrs = resource.get("attributes", {})
    reference = attrs.get("reference_number") or attrs.get("external_reference_number")

    payment = (
        Payment.objects.filter(checkout_session_id=resource_id).first()
        or (Payment.objects.filter(reference=reference).first() if reference else None)
    )
    if not payment:
        return HttpResponse("ignored", status=200)  # unknown/irrelevant event

    if event_type.endswith("payment.paid"):
        method = _extract_method(attrs)
        mark_paid(payment, method=method, session_id=resource_id)
    elif event_type.endswith("payment.failed"):
        mark_failed(payment)
    return HttpResponse("ok", status=200)


def _extract_method(checkout_attrs):
    """Best-effort pull of the payment method from a checkout-session payload."""
    try:
        payments = checkout_attrs.get("payments") or []
        return payments[0]["attributes"]["source"]["type"]
    except (IndexError, KeyError, TypeError):
        return ""


def receipt(request, pk):
    """Electronic receipt for a completed payment (owner or admin)."""
    payment = get_object_or_404(Payment, pk=pk)
    owner = payment.reservation.customer_id == request.user.id
    if not (request.user.is_authenticated and (owner or request.user.is_admin_role)):
        raise PermissionDenied
    if not payment.is_paid:
        messages.info(request, "No receipt yet — this payment is not completed.")
        return redirect("reservations:detail", pk=payment.reservation.pk)
    return render(request, "payments/receipt.html", {"payment": payment})


@customer_required
def history(request):
    payments = Payment.objects.filter(
        reservation__customer=request.user
    ).select_related("reservation", "reservation__slot")
    return render(request, "payments/history.html", {"payments": payments})
