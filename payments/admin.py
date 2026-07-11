from django.contrib import admin

from .models import BillingRecord, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount_display", "status", "method", "paid_at")
    list_filter = ("status", "method", "provider")
    search_fields = ("reference", "checkout_session_id", "payment_intent_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "amount_display", "issued_at")
    search_fields = ("reference", "customer__username")
