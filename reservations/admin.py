from django.contrib import admin

from .models import Reservation


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("code", "slot", "customer", "start_at", "end_at", "status")
    list_filter = ("status", "slot__floor")
    search_fields = ("code", "customer__username", "slot__code")
    date_hierarchy = "start_at"

    # Reservation writes must use the domain service so overlap locks, the
    # one-way state graph, payment pairing, audit logs, and emails cannot be
    # bypassed through Django's generic model editor.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff
