"""Email-verification tokens and delivery.

Uses ``django.core.signing`` (independent of the auth password/last-login hash)
so a token stays valid across logins until it expires or the email changes.
"""

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

TOKEN_SALT = "accounts.email_verify.v1"


def make_email_token(user):
    """Return a signed token binding the user id to their current email."""
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=TOKEN_SALT)


def read_email_token(token, max_age):
    """Return the token payload, or ``None`` if invalid/tampered/expired."""
    try:
        return signing.loads(token, salt=TOKEN_SALT, max_age=max_age)
    except signing.BadSignature:
        return None


def send_verification_email(user):
    """Email the customer a one-time link to confirm their address."""
    if not user.email:
        return
    link = (
        f"{settings.SITE_BASE_URL}"
        f"{reverse('accounts:verify_email', args=[make_email_token(user)])}"
    )
    body = render_to_string(
        "accounts/email/verify_email.txt",
        {"user": user, "link": link, "site_name": settings.SITE_NAME},
    )
    send_mail(
        f"Verify your {settings.SITE_NAME} email",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )
