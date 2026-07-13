"""Thin PayMongo REST client (no official Python SDK).

Only the pieces this app needs: create a Checkout Session (hosted page that
supports GCash / Maya / card) and verify inbound webhook signatures. Payment
simulation is a separate, explicit development/test opt-in; missing
credentials do not select it implicitly.
"""

import base64
import hashlib
import hmac
import time

import requests
from django.conf import settings

API_BASE = "https://api.paymongo.com/v1"
CHECKOUT_METHODS = ["gcash", "paymaya", "card"]
TIMEOUT = 20
WEBHOOK_SIGNATURE_TOLERANCE_SECONDS = 300


class PayMongoError(Exception):
    """Raised when the gateway call fails or returns an unexpected shape."""


def is_configured():
    """True when a live/test secret key is present (real gateway mode)."""
    return bool(settings.PAYMONGO_SECRET_KEY)


def is_simulation_enabled():
    """Return whether the explicit non-production simulator may be used."""
    # All three conditions matter: DEBUG constrains normal environments (while
    # TESTING supports Django's forced DEBUG=False test runner), the flag
    # records operator intent, and missing credentials prevents a real gateway
    # configuration from being accidentally bypassed.
    return bool(
        (settings.DEBUG or getattr(settings, "TESTING", False))
        and settings.PAYMENT_SIMULATION_ENABLED
        and not is_configured()
    )


def expected_livemode():
    """Return the gateway mode represented by the configured secret key.

    ``None`` means the key is missing or does not use PayMongo's documented
    ``sk_test_``/``sk_live_`` prefixes, so a signed delivery cannot be matched
    safely to an environment. The isolated simulator is explicitly test mode.
    """
    key = settings.PAYMONGO_SECRET_KEY
    if key.startswith("sk_live_"):
        return True
    if key.startswith("sk_test_"):
        return False
    if is_simulation_enabled():
        return False
    return None


def _auth_header():
    # PayMongo uses HTTP Basic with the secret key as username, empty password.
    token = base64.b64encode(f"{settings.PAYMONGO_SECRET_KEY}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def create_checkout_session(payment, success_url, cancel_url):
    """Create a hosted checkout session for ``payment``.

    Returns ``(session_id, checkout_url)``. Raises :class:`PayMongoError` on
    any failure so the caller can surface a friendly message.
    """
    body = {
        "data": {
            "attributes": {
                "line_items": [
                    {
                        "name": f"Parking reservation {payment.reference}",
                        "amount": payment.amount_cents,
                        "currency": payment.currency,
                        "quantity": 1,
                    }
                ],
                "payment_method_types": CHECKOUT_METHODS,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "reference_number": payment.reference,
                "description": f"PUP Parking — {payment.reference}",
            }
        }
    }
    try:
        headers = _auth_header()
        # One immutable key per local payment makes external creation safe to
        # retry. PayMongo returns the original result instead of opening a
        # second payable checkout session for the same reservation fee.
        headers["Idempotency-Key"] = str(payment.checkout_idempotency_key)
        resp = requests.post(
            f"{API_BASE}/checkout_sessions",
            json=body,
            headers=headers,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return data["id"], data["attributes"]["checkout_url"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise PayMongoError(str(exc)) from exc


def verify_webhook_signature(request):
    """Validate PayMongo's ``Paymongo-Signature`` header against the raw body.

    Returns True when valid. An unsigned event is accepted only in the explicit
    non-production simulation mode, which keeps isolated tests usable while
    ensuring missing deployment configuration fails closed.
    """
    secret = settings.PAYMONGO_WEBHOOK_SECRET
    if not secret:
        return is_simulation_enabled()
    livemode = expected_livemode()
    if livemode is None:
        return False

    header = request.headers.get("Paymongo-Signature", "")
    # Strip optional whitespace while retaining the exact raw request bytes
    # used by PayMongo when it generated the HMAC.
    parts = {}
    for piece in header.split(","):
        key, separator, value = piece.strip().partition("=")
        if separator:
            parts[key] = value
    timestamp = parts.get("t")
    # A live deployment must never accept a valid test-mode signature (or the
    # reverse), even if a malformed header happens to contain both values.
    provided = parts.get("li" if livemode else "te")
    if not (timestamp and provided):
        return False

    try:
        delivered_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    try:
        tolerance = int(
            getattr(
                settings,
                "PAYMONGO_WEBHOOK_TOLERANCE_SECONDS",
                WEBHOOK_SIGNATURE_TOLERANCE_SECONDS,
            )
        )
    except (TypeError, ValueError):
        return False
    if tolerance <= 0 or abs(time.time() - delivered_at) > tolerance:
        # HMAC alone permits replay forever. A short freshness window keeps a
        # captured signed payload from becoming a reusable financial command.
        return False

    signed_payload = timestamp.encode() + b"." + request.body
    expected = hmac.new(
        secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)
