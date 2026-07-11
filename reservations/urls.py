from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("book/<int:slot_id>/", views.create, name="create"),
    path("history/", views.history, name="history"),
    path("verify/", views.verify, name="verify"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/modify/", views.modify, name="modify"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("<int:pk>/qr/", views.qr, name="qr"),
]
