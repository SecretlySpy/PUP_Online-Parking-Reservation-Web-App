from django.contrib import admin

from .models import Floor, Slot


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ("code", "floor", "slot_type", "status")
    list_filter = ("floor", "slot_type", "status")
    search_fields = ("code",)
