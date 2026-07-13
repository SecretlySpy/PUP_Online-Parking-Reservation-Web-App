from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles, Vehicle
from core.constants import VehicleType
from core.models import ActivityLog
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

    def test_slot_stats_count_unique_current_slots_with_maintenance_precedence(self):
        now = timezone.now()
        # A second active row on the same slot must not inflate a slot KPI.
        Reservation.objects.create(
            customer=self.customer,
            slot=self.s_occ,
            start_at=now - timedelta(minutes=10),
            end_at=now + timedelta(minutes=10),
            status=ReservationStatus.RESERVED,
        )
        # Physical maintenance wins even if stale data says the slot is active.
        Reservation.objects.create(
            customer=self.customer,
            slot=self.s_maint,
            start_at=now - timedelta(minutes=10),
            end_at=now + timedelta(minutes=10),
            status=ReservationStatus.OCCUPIED,
        )
        # Future occupied records do not block availability at the current time.
        Reservation.objects.create(
            customer=self.customer,
            slot=self.s_open,
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(hours=2),
            status=ReservationStatus.OCCUPIED,
        )

        stats = services.slot_stats()

        self.assertEqual(stats["occupied_now"], 1)
        self.assertEqual(stats["maintenance"], 1)
        self.assertEqual(stats["available_now"], 1)


class AccessAndRenderTests(DashboardTestBase):
    def test_customer_denied_dashboard(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        for name in [
            "home",
            "monitor",
            "monitor_partial",
            "reservations",
            "customers",
            "billing",
            "reports",
        ]:
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

    def test_reservation_table_uses_a_filter_preserving_paginator(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dashboard:reservations"),
            {"status": ReservationStatus.OCCUPIED, "floor": self.floor.pk},
        )

        page = response.context["reservations"]
        self.assertEqual(page.paginator.per_page, 50)
        self.assertIn("status=OCCUPIED", response.context["pagination_query"])
        self.assertIn(f"floor={self.floor.pk}", response.context["pagination_query"])


class CustomerManagementTests(DashboardTestBase):
    def setUp(self):
        super().setUp()
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@e.com",
            password=PW,
            role=Roles.EMPLOYEE,
            is_active=False,
            first_name="Elaine",
            last_name="Santos",
            id_number="EMP-204",
        )
        self.other_admin = User.objects.create_user(
            username="other-admin",
            email="other-admin@e.com",
            password=PW,
            role=Roles.ADMIN,
            is_staff=True,
        )

    def test_list_searches_and_filters_customer_accounts_only(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dashboard:customers"),
            {"q": "EMP-204", "role": Roles.EMPLOYEE, "active": "0"},
        )

        self.assertContains(response, "employee@e.com")
        self.assertNotContains(response, self.customer.email)
        self.assertNotContains(response, self.other_admin.email)

    def test_customer_detail_shows_profile_vehicle_and_payment_summary(self):
        Vehicle.objects.create(
            owner=self.customer,
            plate_number="ABC-123",
            vehicle_type=VehicleType.CAR,
            make="Toyota",
            model="Vios",
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("dashboard:customer_detail", args=[self.customer.pk])
        )

        self.assertContains(response, self.customer.email)
        self.assertContains(response, "ABC-123")
        self.assertContains(response, "₱50.00")
        self.assertEqual(response.context["reservations"].paginator.per_page, 20)
        self.assertEqual(response.context["payments"].paginator.per_page, 20)

    def test_admin_can_deactivate_and_reactivate_customer_with_audit_log(self):
        self.client.force_login(self.admin)
        url = reverse("dashboard:customer_toggle_active", args=[self.customer.pk])

        response = self.client.post(url, {"is_active": "0"})
        self.assertRedirects(
            response,
            reverse("dashboard:customer_detail", args=[self.customer.pk]),
        )
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(
            ActivityLog.objects.filter(
                actor=self.admin,
                action="customer.deactivated",
                description__contains=self.customer.username,
            ).exists()
        )

        self.client.post(url, {"is_active": "1"})
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertTrue(
            ActivityLog.objects.filter(
                actor=self.admin,
                action="customer.activated",
            ).exists()
        )

    def test_customer_workflow_cannot_change_admin_accounts(self):
        self.client.force_login(self.admin)
        url = reverse("dashboard:customer_toggle_active", args=[self.other_admin.pk])

        response = self.client.post(url, {"is_active": "0"}, follow=True)

        self.other_admin.refresh_from_db()
        self.assertTrue(self.other_admin.is_active)
        self.assertContains(response, "Administrator accounts cannot be changed here.")
        self.assertFalse(
            ActivityLog.objects.filter(
                description__contains=self.other_admin.username,
                action__startswith="customer.",
            ).exists()
        )

    def test_admin_cannot_deactivate_self_through_customer_workflow(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dashboard:customer_toggle_active", args=[self.admin.pk]),
            {"is_active": "0"},
            follow=True,
        )

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(response, "You cannot deactivate your own account.")

    def test_customer_cannot_access_customer_management(self):
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(reverse("dashboard:customers")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("dashboard:customer_toggle_active", args=[self.employee.pk])
            ).status_code,
            403,
        )


class BillingPaginationTests(DashboardTestBase):
    def test_billing_tables_use_independent_filter_preserving_paginators(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("dashboard:billing"),
            {"status": PaymentStatus.PAID, "payment_page": "1", "record_page": "1"},
        )

        self.assertEqual(response.context["payments"].paginator.per_page, 50)
        self.assertEqual(response.context["records"].paginator.per_page, 50)
        self.assertIn("status=PAID", response.context["payment_query"])
        self.assertIn("record_page=1", response.context["payment_query"])
        self.assertIn("payment_page=1", response.context["record_query"])


class BillingReconciliationTests(DashboardTestBase):
    def test_admin_can_reconcile_pending_payment_as_paid_once(self):
        self.payment.status = PaymentStatus.PENDING
        self.payment.paid_at = None
        self.payment.save(update_fields=["status", "paid_at"])
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("dashboard:payment_status", args=[self.payment.pk]),
                {"status": PaymentStatus.PAID},
            )
        self.assertEqual(response.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PAID)
        self.assertEqual(self.payment.billing_records.count(), 1)
        self.assertTrue(
            ActivityLog.objects.filter(
                actor=self.admin,
                action="payment.paid",
                description__contains=self.payment.reference,
            ).exists()
        )

    def test_admin_failure_reconciliation_names_admin_as_audit_actor(self):
        self.payment.status = PaymentStatus.PENDING
        self.payment.paid_at = None
        self.payment.save(update_fields=["status", "paid_at"])
        self.client.force_login(self.admin)

        self.client.post(
            reverse("dashboard:payment_status", args=[self.payment.pk]),
            {"status": PaymentStatus.FAILED},
        )

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)
        self.assertTrue(
            ActivityLog.objects.filter(
                actor=self.admin,
                action="payment.failed",
                description__contains=self.payment.reference,
            ).exists()
        )

    def test_paid_payment_cannot_be_downgraded(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("dashboard:payment_status", args=[self.payment.pk]),
            {"status": PaymentStatus.FAILED},
            follow=True,
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PAID)
        self.assertContains(response, "immutable")

    def test_customer_cannot_reconcile_payments(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("dashboard:payment_status", args=[self.payment.pk]),
            {"status": PaymentStatus.FAILED},
        )
        self.assertEqual(response.status_code, 403)
