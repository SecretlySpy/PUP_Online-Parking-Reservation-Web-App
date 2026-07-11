from django.contrib import admin

from .models import Reservation


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("code", "slot", "customer", "start_at", "end_at", "status")
    list_filter = ("status", "slot__floor")
    search_fields = ("code", "customer__username", "slot__code")
    readonly_fields = ("code", "created_at", "updated_at")
    date_hierarchy = "start_at"
