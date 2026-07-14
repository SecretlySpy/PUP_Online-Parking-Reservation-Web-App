"""
Django settings for the PUP Online Parking Reservation system.

Configuration is driven by environment variables via ``django-environ`` so the
same code runs on SQLite (default local dev) and MySQL (deployment target)
without edits — set ``DATABASE_URL`` to switch. See ``.env.example``.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment ------------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ["*"]),
    # Default to a local SQLite file so the project runs with zero setup.
    # Point this at MySQL for the real deployment, e.g.
    #   DATABASE_URL=mysql://user:pass@127.0.0.1:3306/pup_parking
    DATABASE_URL=(str, f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
)
# Read a .env file if present (never commit real secrets).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-dev-only-change-me-in-production-0123456789abcdef",
)
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
# Only the dedicated test settings module changes this code-owned sentinel.
# It is intentionally not environment-driven, so deployment configuration
# cannot claim to be the isolated test runtime and reopen test-only paths.
TESTING = False

# CSRF trusted origins (needed once served over a real domain / tunnel).
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])


# --- Applications -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "core",
    "accounts",
    "parking",
    "reservations",
    "payments",
    "dashboard",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves fingerprinted STATIC_ROOT assets in production; user
    # uploads under MEDIA_ROOT still belong behind dedicated object/web storage.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.ActivityLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database ---------------------------------------------------------------
# Parsed from DATABASE_URL. SQLite by default; MySQL via the pymysql shim
# registered in config/__init__.py.
DATABASES = {"default": env.db("DATABASE_URL")}
# MySQL: use utf8mb4 + strict mode when the engine is MySQL.
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].update(
        {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    )


# --- Authentication ---------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Spec requirement: PBKDF2 password hashing. It is Django's default, but we pin
# it explicitly at the top of the list so it is unmistakable in the codebase.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

# Administrator self-registration is disabled unless an operator deliberately
# enables it.  Requiring both a feature flag and a code avoids the previous
# fail-open behaviour where an omitted environment variable meant "no gate".
ADMIN_SIGNUP_ENABLED = env.bool("ADMIN_SIGNUP_ENABLED", default=False)
ADMIN_SIGNUP_CODE = env("ADMIN_SIGNUP_CODE", default="")
# Failed enrollment-code attempts are counted in the audit table by source IP,
# which keeps throttling consistent across multiple application workers.
ADMIN_SIGNUP_MAX_ATTEMPTS = env.int("ADMIN_SIGNUP_MAX_ATTEMPTS", default=5)
ADMIN_SIGNUP_WINDOW_MINUTES = env.int("ADMIN_SIGNUP_WINDOW_MINUTES", default=15)

# Failed sign-in attempts per source IP are counted in the audit table and
# blocked once they exceed the limit within the rolling window.
LOGIN_MAX_ATTEMPTS = env.int("LOGIN_MAX_ATTEMPTS", default=10)
LOGIN_ATTEMPT_WINDOW_MINUTES = env.int("LOGIN_ATTEMPT_WINDOW_MINUTES", default=15)

# How long a customer email-verification link stays valid (seconds; 3 days).
EMAIL_VERIFICATION_MAX_AGE = env.int("EMAIL_VERIFICATION_MAX_AGE", default=259200)


# --- Internationalization ---------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True


# --- Static & media ---------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Keep local development frictionless while production receives
        # immutable, compressed assets with content-hashed filenames.
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Email ------------------------------------------------------------------
# Dev default prints emails (password-reset links, confirmations) to the
# console. Configure real SMTP via env for staging/production.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="PUP Parking <no-reply@pupparking.local>"
)


# --- Payments (PayMongo) ----------------------------------------------------
PAYMONGO_SECRET_KEY = env("PAYMONGO_SECRET_KEY", default="")
PAYMONGO_PUBLIC_KEY = env("PAYMONGO_PUBLIC_KEY", default="")
PAYMONGO_WEBHOOK_SECRET = env("PAYMONGO_WEBHOOK_SECRET", default="")
# Reject signed events outside this freshness window to limit replay exposure.
PAYMONGO_WEBHOOK_TOLERANCE_SECONDS = env.int(
    "PAYMONGO_WEBHOOK_TOLERANCE_SECONDS", default=300
)
# Simulation changes payment state without contacting PayMongo, so it must be
# opted into explicitly and is additionally constrained to DEBUG (or the
# code-owned test sentinel) by the gateway helper.
PAYMENT_SIMULATION_ENABLED = env.bool(
    "PAYMENT_SIMULATION_ENABLED", default=False
)
# Reservation fee in the smallest currency unit (centavos). Default ₱50.00.
RESERVATION_FEE_CENTS = env.int("RESERVATION_FEE_CENTS", default=5000)
# Unpaid holds expire through ``process_reservations`` after this many minutes.
# A zero value disables only grace-based expiry; ended bookings still reconcile.
RESERVATION_PAYMENT_GRACE_MINUTES = env.int(
    "RESERVATION_PAYMENT_GRACE_MINUTES", default=30
)
# Customers may check in slightly early to account for a physical gate queue.
RESERVATION_ARRIVAL_GRACE_MINUTES = env.int(
    "RESERVATION_ARRIVAL_GRACE_MINUTES", default=15
)
# Paid reservations receive one reminder email this many minutes before start.
# A zero/empty value disables reminders.
RESERVATION_REMINDER_MINUTES = env.int("RESERVATION_REMINDER_MINUTES", default=30)


# --- Site / branding --------------------------------------------------------
SITE_NAME = env("SITE_NAME", default="PUP Online Parking Reservation")
SITE_SHORT_NAME = env("SITE_SHORT_NAME", default="PUP Parking")
# Absolute base URL used to build links in emails and QR payloads.
SITE_BASE_URL = env("SITE_BASE_URL", default="http://127.0.0.1:8000")


# --- Security (tightened automatically when DEBUG is off) -------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --- Logging ---------------------------------------------------------------
# Keep application and security events visible in every environment while
# leaving log collection/rotation to the hosting platform.  Avoiding file
# handlers also keeps containers and read-only deployments portable.
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "loggers": {
        # Django request/security logs include rejected hosts, CSRF failures,
        # and server errors that operators need to investigate quickly.
        "django.request": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Project namespaces share one predictable console policy.
        "accounts": {"handlers": ["console"], "level": LOG_LEVEL},
        "payments": {"handlers": ["console"], "level": LOG_LEVEL},
        "reservations": {"handlers": ["console"], "level": LOG_LEVEL},
    },
}


# Import the deployment checks only after every setting they inspect exists.
# Django's check registry then includes these checks for ``check --deploy``
# without requiring the project settings package to masquerade as an app.
from config import checks as deployment_checks  # noqa: E402, F401
