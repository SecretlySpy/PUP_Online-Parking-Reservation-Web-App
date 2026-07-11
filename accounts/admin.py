from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Vehicle


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "get_full_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Parking profile",
            {
                "fields": (
                    "role",
                    "middle_name",
                    "id_number",
                    "contact_number",
                    "address",
                )
            },
        ),
    )


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "vehicle_type", "owner", "created_at")
    list_filter = ("vehicle_type",)
    search_fields = ("plate_number", "owner__username", "owner__email")
