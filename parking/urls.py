from django.urls import path

from . import views

app_name = "parking"

urlpatterns = [
    # Public facility guide
    path("facility/", views.facility, name="facility"),
    # Customer real-time slot monitoring
    path("slots/", views.slots, name="slots"),
    path("slots/grid/", views.slots_partial, name="slots_partial"),
    path("api/slots/", views.slots_api, name="slots_api"),
    # Admin floor management
    path("manage/floors/", views.floor_list, name="floor_list"),
    path("manage/floors/add/", views.floor_add, name="floor_add"),
    path("manage/floors/<int:pk>/edit/", views.floor_edit, name="floor_edit"),
    # Admin slot management
    path("manage/slots/", views.slot_list, name="slot_list"),
    path("manage/slots/add/", views.slot_add, name="slot_add"),
    path("manage/slots/<int:pk>/edit/", views.slot_edit, name="slot_edit"),
    path("manage/slots/<int:pk>/toggle/", views.slot_toggle, name="slot_toggle"),
]
