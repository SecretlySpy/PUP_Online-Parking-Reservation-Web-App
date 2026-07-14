"""Hermetic Django settings used by the automated test suite.

Run tests with ``python manage.py test --settings=config.settings_test``.
These values are explicit so a developer's ``.env`` cannot silently redirect
tests to MySQL, HTTPS, SMTP, or a real payment gateway.
"""

from .settings import *  # noqa: F403


# Tests intentionally exercise development-only paths in an isolated process.
DEBUG = True
TESTING = True

# WhiteNoise is exercised by collectstatic/deployment checks, not request unit
# tests.  Removing it keeps the suite independent of a prebuilt STATIC_ROOT.
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
SECRET_KEY = "test-only-secret-key-with-sufficient-length-0123456789"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = []

# An in-memory SQLite database makes the suite independent of local services
# and ensures no developer or deployment records can be modified by a test.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Capture mail in ``mail.outbox`` and prevent all network delivery.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "PUP Parking Tests <tests@pupparking.invalid>"

# Admin registration and payment simulation remain testable only because this
# dedicated settings module opts into them with non-production values.
ADMIN_SIGNUP_ENABLED = True
ADMIN_SIGNUP_CODE = "test-admin-signup-code-2026"
PAYMONGO_SECRET_KEY = ""
PAYMONGO_PUBLIC_KEY = ""
PAYMONGO_WEBHOOK_SECRET = ""
PAYMENT_SIMULATION_ENABLED = True
RESERVATION_PAYMENT_GRACE_MINUTES = 30
RESERVATION_ARRIVAL_GRACE_MINUTES = 15
RESERVATION_REMINDER_MINUTES = 30
RESERVATION_FEE_CENTS = 5000
LOGIN_MAX_ATTEMPTS = 10
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
EMAIL_VERIFICATION_MAX_AGE = 259200
SITE_BASE_URL = "http://testserver"

# Undo production transport flags that may have been populated while importing
# base settings from a host environment with DEBUG disabled.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# A local-memory cache prevents cross-run state and external cache dependency.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pup-parking-tests",
    }
}

# Tests render templates without running collectstatic.  The plain storage
# backend keeps URL generation hermetic while production still uses the
# compressed manifest backend from the base settings module.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Expected 403/404 responses are test assertions, not operator incidents.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
    "loggers": {
        "django": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "accounts": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "payments": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "reservations": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
    },
}
