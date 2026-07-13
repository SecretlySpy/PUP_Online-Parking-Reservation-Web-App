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
    path(
        "billing/<int:pk>/status/",
        views.payment_update_status,
        name="payment_status",
    ),
    path("customers/", views.customers, name="customers"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path(
        "customers/<int:pk>/active/",
        views.customer_toggle_active,
        name="customer_toggle_active",
    ),
    path("reports/", views.reports, name="reports"),
]
