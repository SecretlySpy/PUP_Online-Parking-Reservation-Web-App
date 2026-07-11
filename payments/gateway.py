"""Thin PayMongo REST client (no official Python SDK).

Only the pieces this app needs: create a Checkout Session (hosted page that
supports GCash / Maya / card) and verify inbound webhook signatures. When
``PAYMONGO_SECRET_KEY`` is unset the app runs in *simulation* mode (see
``payments.views.simulate``) and this client is not called.
"""

import base64
import hashlib
import hmac

import requests
from django.conf import settings

API_BASE = "https://api.paymongo.com/v1"
CHECKOUT_METHODS = ["gcash", "paymaya", "card"]
TIMEOUT = 20


class PayMongoError(Exception):
    """Raised when the gateway call fails or returns an unexpected shape."""


def is_configured():
    """True when a live/test secret key is present (real gateway mode)."""
    return bool(settings.PAYMONGO_SECRET_KEY)


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
        resp = requests.post(
            f"{API_BASE}/checkout_sessions",
            json=body,
            headers=_auth_header(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return data["id"], data["attributes"]["checkout_url"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise PayMongoError(str(exc)) from exc


def verify_webhook_signature(request):
    """Validate PayMongo's ``Paymongo-Signature`` header against the raw body.

    Returns True when valid. If no webhook secret is configured (dev), returns
    True (verification disabled) — set ``PAYMONGO_WEBHOOK_SECRET`` in prod.
    """
    secret = settings.PAYMONGO_WEBHOOK_SECRET
    if not secret:
        return True
    header = request.headers.get("Paymongo-Signature", "")
    parts = dict(
        piece.split("=", 1) for piece in header.split(",") if "=" in piece
    )
    timestamp = parts.get("t")
    # 'te' = test-mode signature, 'li' = live-mode signature.
    provided = parts.get("te") or parts.get("li")
    if not (timestamp and provided):
        return False
    signed_payload = f"{timestamp}.{request.body.decode()}".encode()
    expected = hmac.new(
        secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)
