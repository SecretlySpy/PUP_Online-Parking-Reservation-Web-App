"""Root URL configuration for public, customer, payment, and admin routes."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


def _development_admin_patterns():
    """Expose Django's generic editor only in a debug runtime."""
    if not settings.DEBUG:
        return []
    return [path("django-admin/", admin.site.urls)]


urlpatterns = _development_admin_patterns() + [
    path("accounts/", include("accounts.urls")),
    path("parking/", include("parking.urls")),
    path("reservations/", include("reservations.urls")),
    path("payments/", include("payments.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("core.urls")),
]

# Django admin is retained as a local inspection tool only. Production writes
# must pass through the dashboard and domain services that enforce transitions,
# audit attribution, billing, and notification invariants.
if settings.DEBUG:
    # Serve local assets only in development. Production static files are
    # handled by WhiteNoise and media belongs behind dedicated storage.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
