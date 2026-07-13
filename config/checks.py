"""Deployment checks for privileged registration and payment configuration."""

from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, register


MINIMUM_ADMIN_CODE_LENGTH = 16
UNSAFE_MARKERS = ("change-me", "example", "xxx")


def _looks_like_placeholder(value):
    """Return whether a configured secret still resembles example text."""
    normalized = value.strip().lower()
    return any(marker in normalized for marker in UNSAFE_MARKERS)


@register(Tags.security, deploy=True)
def check_privileged_configuration(app_configs, **kwargs):
    """Reject deployment settings that reopen privileged or payment paths."""
    errors = []

    # A disabled registration endpoint is safe without a code. When enabled,
    # enforce enough entropy-bearing space and reject copied placeholders.
    admin_code = settings.ADMIN_SIGNUP_CODE
    if settings.ADMIN_SIGNUP_ENABLED and (
        len(admin_code) < MINIMUM_ADMIN_CODE_LENGTH
        or _looks_like_placeholder(admin_code)
    ):
        errors.append(
            Error(
                "Administrator self-registration is enabled without a strong "
                "access code.",
                hint=(
                    "Set ADMIN_SIGNUP_CODE to a non-placeholder value with at "
                    f"least {MINIMUM_ADMIN_CODE_LENGTH} characters, or set "
                    "ADMIN_SIGNUP_ENABLED=False."
                ),
                id="parking.E001",
            )
        )

    if settings.ADMIN_SIGNUP_ENABLED and (
        settings.ADMIN_SIGNUP_MAX_ATTEMPTS < 1
        or settings.ADMIN_SIGNUP_WINDOW_MINUTES < 1
    ):
        errors.append(
            Error(
                "Administrator enrollment throttling is disabled or invalid.",
                hint=(
                    "Set ADMIN_SIGNUP_MAX_ATTEMPTS and "
                    "ADMIN_SIGNUP_WINDOW_MINUTES to positive integers."
                ),
                id="parking.E004",
            )
        )

    # Deployment must use the real gateway. Merely setting the simulation flag
    # is an unsafe configuration even though the runtime helper also checks
    # DEBUG, because an operator likely intended a production payment path.
    if settings.PAYMENT_SIMULATION_ENABLED:
        errors.append(
            Error(
                "Payment simulation is enabled in deployment settings.",
                hint="Set PAYMENT_SIMULATION_ENABLED=False before deployment.",
                id="parking.E002",
            )
        )

    required_payment_settings = {
        "PAYMONGO_SECRET_KEY": settings.PAYMONGO_SECRET_KEY,
        "PAYMONGO_PUBLIC_KEY": settings.PAYMONGO_PUBLIC_KEY,
        "PAYMONGO_WEBHOOK_SECRET": settings.PAYMONGO_WEBHOOK_SECRET,
    }
    missing_or_placeholder = [
        name
        for name, value in required_payment_settings.items()
        if not value.strip() or _looks_like_placeholder(value)
    ]
    secret_key = settings.PAYMONGO_SECRET_KEY
    public_key = settings.PAYMONGO_PUBLIC_KEY
    secret_mode = (
        "live" if secret_key.startswith("sk_live_")
        else "test" if secret_key.startswith("sk_test_")
        else ""
    )
    public_mode = (
        "live" if public_key.startswith("pk_live_")
        else "test" if public_key.startswith("pk_test_")
        else ""
    )
    if not secret_mode or not public_mode or secret_mode != public_mode:
        missing_or_placeholder.append("PAYMONGO_KEY_MODE")
    if settings.PAYMONGO_WEBHOOK_TOLERANCE_SECONDS < 1:
        missing_or_placeholder.append("PAYMONGO_WEBHOOK_TOLERANCE_SECONDS")
    if missing_or_placeholder:
        errors.append(
            Error(
                "PayMongo deployment configuration is incomplete or unsafe: "
                + ", ".join(missing_or_placeholder),
                hint="Configure real PayMongo credentials and webhook secret.",
                id="parking.E003",
            )
        )

    # QR and email links must resolve to the public HTTPS deployment rather
    # than a loopback development server.
    site_url = urlparse(settings.SITE_BASE_URL)
    if (
        site_url.scheme != "https"
        or not site_url.hostname
        or site_url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        errors.append(
            Error(
                "SITE_BASE_URL is not a public HTTPS origin.",
                hint="Set SITE_BASE_URL to the canonical HTTPS deployment URL.",
                id="parking.E005",
            )
        )

    # Console/local-memory backends can leak sensitive account links into logs
    # or silently discard them, so they are never acceptable for deployment.
    unsafe_email_backends = {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
    smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
    if (
        settings.EMAIL_TIMEOUT < 1
        or settings.EMAIL_BACKEND in unsafe_email_backends
        or (
            settings.EMAIL_BACKEND == smtp_backend
            and not settings.EMAIL_HOST.strip()
        )
    ):
        errors.append(
            Error(
                "Production email delivery is not configured.",
                hint="Configure a real email backend and its required host credentials.",
                id="parking.E006",
            )
        )

    return errors
