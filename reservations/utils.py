"""Reservation codes, signed QR verification payloads, and QR image bytes.

The QR encodes a *signed* token (via ``django.core.signing``) rather than a raw
id, so a code cannot be forged or altered without the server's SECRET_KEY. On
arrival staff open the verify URL carrying this token; the server unsigns it to
resolve the reservation.
"""

import io
import secrets

import qrcode
from django.conf import settings
from django.core import signing

# Namespaces the signature so these tokens can't be replayed against other
# signed payloads elsewhere in the project.
QR_SALT = "reservations.qr.v1"


def make_reservation_code():
    """Return a short, human-readable, unique-enough code, e.g. ``PUP-9F3A1C``."""
    return "PUP-" + secrets.token_hex(3).upper()


def sign_reservation(reservation):
    """Produce the tamper-proof token embedded in the QR for a reservation."""
    return signing.dumps(
        {"id": reservation.pk, "code": reservation.code}, salt=QR_SALT
    )


def unsign_token(token, max_age=None):
    """Reverse :func:`sign_reservation`.

    Returns the payload dict, or ``None`` if the token is invalid, tampered, or
    (when ``max_age`` given) expired.
    """
    try:
        return signing.loads(token, salt=QR_SALT, max_age=max_age)
    except signing.BadSignature:
        return None


def qr_png_bytes(data):
    """Render ``data`` (str) into PNG bytes for an <img> or HTTP response."""
    img = qrcode.make(data)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def verification_url(reservation):
    """Absolute URL staff hit to verify a reservation on arrival (encoded in QR)."""
    from django.urls import reverse

    token = sign_reservation(reservation)
    return f"{settings.SITE_BASE_URL}{reverse('reservations:verify')}?t={token}"
