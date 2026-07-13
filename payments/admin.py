from django.contrib import admin

from .models import BillingRecord, PayMongoWebhookEvent, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount_display", "status", "method", "paid_at")
    list_filter = ("status", "method", "provider")
    search_fields = ("reference", "checkout_session_id", "payment_intent_id")

    # Financial state is reconciled by signed webhooks or the controlled
    # dashboard action; generic admin writes would skip receipts and auditing.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "amount_display", "issued_at")
    search_fields = ("reference", "customer__username")

    # Billing rows are immutable receipt snapshots created by payment services.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff


@admin.register(PayMongoWebhookEvent)
class PayMongoWebhookEventAdmin(admin.ModelAdmin):
    """Read-only provider-event evidence for payment incident analysis."""

    list_display = (
        "event_id",
        "event_type",
        "livemode",
        "outcome",
        "payment",
        "received_at",
    )
    list_filter = ("livemode", "outcome", "event_type")
    search_fields = ("event_id", "detail", "payment__reference")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff
