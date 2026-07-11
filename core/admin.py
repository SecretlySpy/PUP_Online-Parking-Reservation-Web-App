from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_label", "action", "description")
    list_filter = ("action",)
    search_fields = ("actor_label", "action", "description")
    readonly_fields = ("actor", "actor_label", "action", "description", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False
