from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("monitor/", views.monitor, name="monitor"),
    path("monitor/grid/", views.monitor_partial, name="monitor_partial"),
    path("reservations/", views.reservations_manager, name="reservations"),
    path(
        "reservations/<int:pk>/status/",
        views.reservation_update_status,
        name="reservation_status",
    ),
    path("billing/", views.billing, name="billing"),
    path("reports/", views.reports, name="reports"),
]
