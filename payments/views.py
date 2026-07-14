import json
import logging

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import customer_required
from reservations.models import Reservation

from . import gateway
from .models import (
    PayMongoWebhookEvent,
    Payment,
    WebhookOutcome,
)
from .services import PaymentTransitionError, mark_failed, mark_paid, prepare_payment


logger = logging.getLogger(__name__)


def _abs_url(path):
    """Build an absolute URL (gateway requires absolute success/cancel URLs)."""
    return f"{settings.SITE_BASE_URL}{path}"


@customer_required
@require_POST
def start(request, reservation_id):
    """Begin payment through a CSRF-protected, mutation-safe POST endpoint."""
    reservation = get_object_or_404(
        Reservation, pk=reservation_id, customer=request.user
    )
    try:
        payment = prepare_payment(reservation, request=request)
    except PaymentTransitionError as exc:
        messages.error(request, exc.messages[0])
        return redirect("reservations:detail", pk=reservation.pk)
    if payment.is_paid:
        messages.info(request, "This reservation is already paid.")
        return redirect("reservations:detail", pk=reservation.pk)

    # Dev/no-keys mode: use the built-in simulated gateway page.
    if gateway.is_simulation_enabled():
        return redirect("payments:simulate", pk=payment.pk)
    if not gateway.is_configured():
        # Production must never turn missing gateway credentials into a free
        # success button.  Keep the reservation pending and fail visibly.
        logger.error("Payment checkout requested while PayMongo is unconfigured")
        messages.error(
            request,
            "Online payment is temporarily unavailable. Contact parking administration.",
        )
        return redirect("reservations:detail", pk=reservation.pk)

    # Real PayMongo hosted checkout.
    success = _abs_url(reverse("payments:return") + f"?pk={payment.pk}")
    cancel = _abs_url(reverse("reservations:detail", args=[reservation.pk]))
    try:
        session_id, checkout_url = gateway.create_checkout_session(
            payment, success, cancel
        )
    except gateway.PayMongoError:
        logger.exception("PayMongo checkout-session creation failed")
        messages.error(request, "Could not reach the payment gateway. Try again.")
        return redirect("reservations:detail", pk=reservation.pk)
    payment.checkout_session_id = session_id
    payment.save(update_fields=["checkout_session_id", "updated_at"])
    return redirect(checkout_url)


@customer_required
def simulate(request, pk):
    """Dev-only simulated gateway (active when no PayMongo keys are set)."""
    if not gateway.is_simulation_enabled():
        raise PermissionDenied  # simulation is an explicit test/development feature
    payment = get_object_or_404(Payment, pk=pk, reservation__customer=request.user)
    if request.method == "POST":
        if request.POST.get("action") == "success":
            mark_paid(
                payment,
                method="simulated",
                actor=request.user,
                request=request,
            )
            messages.success(request, "Payment successful (simulated).")
            return redirect("payments:receipt", pk=payment.pk)
        mark_failed(payment, actor=request.user, request=request)
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
    """Validate, deduplicate, and reconcile a PayMongo checkout event."""
    if not gateway.verify_webhook_signature(request):
        return JsonResponse({"status": "unauthorized"}, status=401)
    try:
        event = json.loads(request.body.decode())
        envelope = event["data"]
        event_id = envelope["id"]
        attributes = envelope["attributes"]
        event_type = attributes["type"]
        livemode = attributes["livemode"]
        resource = attributes.get("data", {})
    except (TypeError, UnicodeDecodeError, ValueError, KeyError):
        return HttpResponseBadRequest("bad payload")

    # Persisted provider IDs are the cross-process idempotency boundary. Reject
    # oversized/malformed identifiers before they can cause a database error.
    if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
        return HttpResponseBadRequest("bad event id")
    if not isinstance(event_type, str) or not event_type or len(event_type) > 64:
        return HttpResponseBadRequest("bad event type")
    if type(livemode) is not bool:  # ``1`` must not silently become live mode.
        return HttpResponseBadRequest("bad livemode")

    with transaction.atomic():
        delivery, created = PayMongoWebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type,
                "livemode": livemode,
            },
        )
        if not created:
            # The original transaction already owns all financial side effects.
            return JsonResponse({"status": "duplicate"})

        expected_livemode = gateway.expected_livemode()
        if expected_livemode is None or livemode is not expected_livemode:
            return _finish_webhook(
                delivery,
                WebhookOutcome.REJECTED,
                "event mode does not match gateway configuration",
            )

        # This integration creates hosted Checkout Sessions and subscribes only
        # to their paid event. Suffix matching would also accept unrelated Link
        # or future event families with different reconciliation semantics.
        if event_type != "checkout_session.payment.paid":
            return _finish_webhook(
                delivery,
                WebhookOutcome.IGNORED,
                "unsupported event type",
            )

        validation = _validated_checkout_payment(resource)
        if validation["error"]:
            return _finish_webhook(
                delivery,
                WebhookOutcome.REJECTED,
                validation["error"],
            )

        resource_id = validation["session_id"]
        reference = validation["reference"]
        # Session ID is the primary correlation key because it was returned by
        # PayMongo and stored before the customer reached hosted checkout. A
        # reference-only fallback could mark a duplicate/imported row as paid.
        try:
            payment = Payment.objects.get(checkout_session_id=resource_id)
        except Payment.DoesNotExist:
            return _finish_webhook(
                delivery,
                WebhookOutcome.REJECTED,
                "unknown checkout session",
            )
        except Payment.MultipleObjectsReturned:
            # Empty/legacy gateway IDs are not database-unique, so fail closed
            # if an import ever created ambiguous non-empty session mappings.
            return _finish_webhook(
                delivery,
                WebhookOutcome.REJECTED,
                "ambiguous checkout session",
            )
        delivery.payment = payment

        mismatch = _payment_mismatch(payment, validation)
        if mismatch:
            return _finish_webhook(
                delivery,
                WebhookOutcome.REJECTED,
                mismatch,
            )

        mark_paid(
            payment,
            method=validation["method"],
            intent_id=validation["intent_id"],
            session_id=resource_id,
        )
        return _finish_webhook(
            delivery,
            WebhookOutcome.PROCESSED,
            f"payment {payment.pk} reconciled for {reference}",
        )


def _finish_webhook(delivery, outcome, detail):
    """Persist one terminal result and acknowledge the verified delivery."""
    delivery.outcome = outcome
    delivery.detail = detail[:255]
    delivery.save(update_fields=["payment", "outcome", "detail"])
    if outcome == WebhookOutcome.REJECTED:
        logger.warning(
            "Rejected PayMongo webhook event_id=%s detail=%s",
            delivery.event_id,
            delivery.detail,
        )
    return JsonResponse({"status": outcome.lower()})


def _validated_checkout_payment(resource):
    """Extract the paid attempt fields required for safe reconciliation."""
    invalid = {
        "error": "malformed checkout resource",
        "session_id": "",
        "reference": "",
        "amount": None,
        "currency": "",
        "method": "",
        "intent_id": "",
    }
    if not isinstance(resource, dict):
        return invalid

    resource_id = resource.get("id", "")
    attrs = resource.get("attributes", {})
    if (
        not isinstance(resource_id, str)
        or not resource_id
        or len(resource_id) > 128
        or not isinstance(attrs, dict)
    ):
        return invalid
    resource_type = resource.get("type")
    if resource_type not in (None, "checkout_session"):
        return {**invalid, "error": "unexpected resource type"}

    reference = attrs.get("reference_number")
    payment_attempts = attrs.get("payments")
    if not isinstance(reference, str) or not reference:
        return {**invalid, "error": "missing checkout reference"}
    if not isinstance(payment_attempts, list):
        return {**invalid, "error": "missing checkout payment details"}

    paid_attempt = None
    for attempt in reversed(payment_attempts):
        attempt_attrs = attempt.get("attributes", {}) if isinstance(attempt, dict) else {}
        if attempt_attrs.get("status") == "paid":
            paid_attempt = attempt_attrs
            break
    if paid_attempt is None:
        return {**invalid, "error": "checkout has no paid attempt"}

    source = paid_attempt.get("source") or {}
    payment_intent = attrs.get("payment_intent") or {}
    return {
        "error": "",
        "session_id": resource_id,
        "reference": reference,
        "amount": paid_attempt.get("amount"),
        "currency": paid_attempt.get("currency"),
        "method": source.get("type", "") if isinstance(source, dict) else "",
        "intent_id": (
            payment_intent.get("id", "")
            if isinstance(payment_intent, dict)
            else ""
        ),
    }


def _payment_mismatch(payment, checkout):
    """Return the first financial/session mismatch, or an empty string."""
    if payment.provider.lower() != "paymongo":
        return "payment provider mismatch"
    if checkout["session_id"] != payment.checkout_session_id:
        return "checkout session mismatch"
    if checkout["reference"] != payment.reference:
        return "checkout reference mismatch"
    if type(checkout["amount"]) is not int or checkout["amount"] != payment.amount_cents:
        return "checkout amount mismatch"
    currency = checkout["currency"]
    if not isinstance(currency, str) or currency.upper() != payment.currency.upper():
        return "checkout currency mismatch"
    return ""


def _receipt_payment_or_deny(request, pk):
    """Fetch a payment the requester may view a receipt for, or 403."""
    payment = get_object_or_404(
        Payment.objects.select_related(
            "reservation", "reservation__slot__floor", "reservation__customer"
        ),
        pk=pk,
    )
    owner = payment.reservation.customer_id == request.user.id
    if not (request.user.is_authenticated and (owner or request.user.is_admin_role)):
        raise PermissionDenied
    return payment


def receipt(request, pk):
    """Electronic receipt for a completed payment (owner or admin)."""
    payment = _receipt_payment_or_deny(request, pk)
    if not payment.is_paid:
        messages.info(request, "No receipt yet — this payment is not completed.")
        return redirect("reservations:detail", pk=payment.reservation.pk)
    return render(request, "payments/receipt.html", {"payment": payment})


def receipt_pdf(request, pk):
    """Downloadable PDF version of the receipt (owner or admin, paid only)."""
    from .receipts import build_receipt_pdf

    payment = _receipt_payment_or_deny(request, pk)
    if not payment.is_paid:
        raise Http404("No receipt for an incomplete payment.")
    response = HttpResponse(build_receipt_pdf(payment), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="receipt-{payment.reference or payment.pk}.pdf"'
    )
    return response


@customer_required
def history(request):
    payments = Payment.objects.filter(
        reservation__customer=request.user
    ).select_related("reservation", "reservation__slot")
    page = Paginator(payments, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "payments/history.html",
        {"payments": page.object_list, "page_obj": page},
    )
