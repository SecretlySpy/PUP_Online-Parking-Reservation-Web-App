from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.constants import VehicleType
from parking.models import Floor, Slot, SlotStatus
from payments.models import Payment, PaymentStatus
from reservations.models import Reservation, ReservationStatus

from . import services

User = get_user_model()
PW = "Str0ngPass!23"


class DashboardTestBase(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="Ground", code="G", sort_order=1)
        self.s_open = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.s_occ = Slot.objects.create(floor=self.floor, code="G-02", slot_type=VehicleType.CAR)
        self.s_maint = Slot.objects.create(
            floor=self.floor, code="G-03", slot_type=VehicleType.CAR, status=SlotStatus.MAINTENANCE
        )
        self.admin = User.objects.create_user(
            username="adm", email="adm@e.com", password=PW, role=Roles.ADMIN, is_staff=True
        )
        self.customer = User.objects.create_user(
            username="cust", email="cust@e.com", password=PW, role=Roles.STUDENT
        )
        now = timezone.now()
        # An OCCUPIED reservation covering "now" on slot 2.
        self.res = Reservation.objects.create(
            customer=self.customer, slot=self.s_occ,
            start_at=now - timedelta(minutes=30), end_at=now + timedelta(hours=1),
            status=ReservationStatus.OCCUPIED,
        )
        # A completed, paid payment for revenue stats.
        self.payment = Payment.objects.create(
            reservation=self.res, amount_cents=5000, reference=self.res.code,
            status=PaymentStatus.PAID, paid_at=now,
        )


class ServiceTests(DashboardTestBase):
    def test_slot_stats(self):
        stats = services.slot_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["maintenance"], 1)
        self.assertEqual(stats["occupied_now"], 1)
        self.assertEqual(stats["available_now"], 1)  # 3 - 1 maint - 1 occ

    def test_payment_stats_revenue(self):
        stats = services.payment_stats()
        self.assertEqual(stats["revenue_cents"], 5000)
        self.assertEqual(stats["by_status"]["PAID"], 1)

    def test_monitor_status_precedence(self):
        by_code = {s.code: s.monitor_status for s in services.monitor_slots()}
        self.assertEqual(by_code["G-01"], "available")
        self.assertEqual(by_code["G-02"], "occupied")
        self.assertEqual(by_code["G-03"], "maintenance")


class AccessAndRenderTests(DashboardTestBase):
    def test_customer_denied_dashboard(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        for name in ["home", "monitor", "monitor_partial", "reservations", "billing", "reports"]:
            resp = self.client.get(reverse(f"dashboard:{name}"))
            self.assertEqual(resp.status_code, 200, name)

    def test_reports_shows_revenue(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard:reports"))
        self.assertContains(resp, "₱50.00")


class ReservationManagerTests(DashboardTestBase):
    def test_admin_can_update_reservation_status(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("dashboard:reservation_status", args=[self.res.pk]),
            {"status": ReservationStatus.COMPLETED},
        )
        self.assertEqual(resp.status_code, 302)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, ReservationStatus.COMPLETED)

    def test_customer_cannot_update_status(self):
        self.client.force_login(self.customer)
        resp = self.client.post(
            reverse("dashboard:reservation_status", args=[self.res.pk]),
            {"status": ReservationStatus.CANCELLED},
        )
        self.assertEqual(resp.status_code, 403)
