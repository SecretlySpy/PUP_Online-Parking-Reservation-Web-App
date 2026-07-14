"""Audit-log viewer and CSV export tests."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.constants import VehicleType
from core.models import log_activity
from parking.models import Floor, Slot
from payments.models import Payment, PaymentStatus
from reservations.models import Reservation

User = get_user_model()
PW = "Str0ngPass!23"


class AuditAndCsvTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="csvadmin", email="csv@e.com", password=PW,
            role=Roles.ADMIN, is_staff=True,
        )
        self.customer = User.objects.create_user(
            username="csvcust", email="csvc@e.com", password=PW, role=Roles.STUDENT
        )
        floor = Floor.objects.create(name="C", code="CS", sort_order=95)
        slot = Slot.objects.create(floor=floor, code="CS-01", slot_type=VehicleType.CAR)
        start = timezone.now() + timedelta(hours=3)
        self.res = Reservation.objects.create(
            customer=self.customer, slot=slot, start_at=start, end_at=start + timedelta(hours=1)
        )
        Payment.objects.create(
            reservation=self.res, amount_cents=5000, reference=self.res.code,
            status=PaymentStatus.PAID, paid_at=timezone.now(),
        )
        log_activity("test.audit_event", "AUDIT-MARKER", actor=self.admin)
        self.client.force_login(self.admin)

    def test_activity_log_page_renders_and_filters(self):
        resp = self.client.get(reverse("dashboard:activity_log"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AUDIT-MARKER")
        # Filtering by a non-matching action hides it.
        resp2 = self.client.get(reverse("dashboard:activity_log"), {"action": "nope.none"})
        self.assertNotContains(resp2, "AUDIT-MARKER")

    def test_activity_log_csv_export(self):
        resp = self.client.get(reverse("dashboard:activity_log"), {"export": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("AUDIT-MARKER", resp.content.decode())

    def test_reservations_csv_export(self):
        resp = self.client.get(reverse("dashboard:reservations"), {"export": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn(self.res.code, resp.content.decode())

    def test_billing_csv_export(self):
        resp = self.client.get(reverse("dashboard:billing"), {"export": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn(self.res.code, resp.content.decode())
