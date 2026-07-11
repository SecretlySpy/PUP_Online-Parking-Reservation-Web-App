"""Root URL configuration for the PUP Online Parking Reservation system.

App URLconfs are wired in as each phase lands (parking, reservations,
payments, dashboard follow in later phases).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),  # dev-time DB inspection only
    path("accounts/", include("accounts.urls")),
    path("parking/", include("parking.urls")),
    path("reservations/", include("reservations.urls")),
    path("payments/", include("payments.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("core.urls")),
]

# Serve user-uploaded media (e.g. QR images) during development.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
