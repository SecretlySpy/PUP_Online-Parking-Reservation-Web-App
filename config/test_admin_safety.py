"""Regression checks for privileged generic-model administration surfaces."""

from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase, override_settings

from config.urls import _development_admin_patterns
from payments.admin import (
    BillingRecordAdmin,
    PayMongoWebhookEventAdmin,
    PaymentAdmin,
)
from payments.models import BillingRecord, PayMongoWebhookEvent, Payment
from reservations.admin import ReservationAdmin
from reservations.models import Reservation


class DomainAdminSafetyTests(SimpleTestCase):
    """Domain records remain observable without bypassing service invariants."""

    def setUp(self):
        self.request = RequestFactory().get("/django-admin/")
        self.request.user = SimpleNamespace(is_active=True, is_staff=True)

    def test_financial_and_reservation_admins_are_view_only(self):
        model_admins = (
            ReservationAdmin(Reservation, admin.site),
            PaymentAdmin(Payment, admin.site),
            BillingRecordAdmin(BillingRecord, admin.site),
            PayMongoWebhookEventAdmin(PayMongoWebhookEvent, admin.site),
        )
        for model_admin in model_admins:
            with self.subTest(model=model_admin.model._meta.label):
                self.assertTrue(model_admin.has_view_permission(self.request))
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(
                    model_admin.has_change_permission(self.request, obj=None)
                )
                self.assertFalse(
                    model_admin.has_delete_permission(self.request, obj=None)
                )

    @override_settings(DEBUG=False)
    def test_django_admin_routes_are_absent_outside_debug(self):
        self.assertEqual(_development_admin_patterns(), [])
