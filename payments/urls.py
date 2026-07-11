from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("start/<int:reservation_id>/", views.start, name="start"),
    path("simulate/<int:pk>/", views.simulate, name="simulate"),
    path("return/", views.gateway_return, name="return"),
    path("webhook/", views.webhook, name="webhook"),
    path("receipt/<int:pk>/", views.receipt, name="receipt"),
    path("history/", views.history, name="history"),
]
