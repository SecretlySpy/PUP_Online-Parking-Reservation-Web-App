import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles, Vehicle
from core.constants import VehicleType
from parking.models import Floor, Slot
from reservations.models import Reservation

from .models import BillingRecord, Payment, PaymentStatus
from .services import get_or_create_payment, mark_paid

User = get_user_model()
PW = "Str0ngPass!23"


class PaymentTestBase(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.user = User.objects.create_user(
            username="cust", email="cust@e.com", password=PW, role=Roles.STUDENT
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.user, plate_number="ABC123", vehicle_type=VehicleType.CAR
        )
        start = timezone.now() + timedelta(hours=2)
        self.reservation = Reservation.objects.create(
            customer=self.user, slot=self.slot, vehicle=self.vehicle,
            start_at=start, end_at=start + timedelta(hours=1),
        )


class PaymentServiceTests(PaymentTestBase):
    def test_get_or_create_uses_reservation_fee_and_code(self):
        payment = get_or_create_payment(self.reservation)
        self.assertEqual(payment.amount_cents, self.reservation.fee_cents)
        self.assertEqual(payment.reference, self.reservation.code)
        # Idempotent — same row returned.
        self.assertEqual(get_or_create_payment(self.reservation).pk, payment.pk)

    def test_mark_paid_issues_billing_and_email_once(self):
        payment = get_or_create_payment(self.reservation)
        mark_paid(payment, method="gcash")
        mark_paid(payment, method="gcash")  # duplicate (e.g. webhook retry)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PAID)
        self.assertEqual(BillingRecord.objects.filter(payment=payment).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.reservation.code, mail.outbox[0].body)


class SimulatedCheckoutTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_start_redirects_to_simulator_when_unconfigured(self):
        resp = self.client.get(reverse("payments:start", args=[self.reservation.pk]))
        payment = Payment.objects.get(reservation=self.reservation)
        self.assertRedirects(resp, reverse("payments:simulate", args=[payment.pk]))

    def test_simulated_success_marks_paid_and_shows_receipt(self):
        self.client.get(reverse("payments:start", args=[self.reservation.pk]))
        payment = Payment.objects.get(reservation=self.reservation)
        resp = self.client.post(
            reverse("payments:simulate", args=[payment.pk]), {"action": "success"}
        )
        self.assertRedirects(resp, reverse("payments:receipt", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertTrue(payment.is_paid)

    def test_simulated_failure_marks_failed(self):
        self.client.get(reverse("payments:start", args=[self.reservation.pk]))
        payment = Payment.objects.get(reservation=self.reservation)
        self.client.post(reverse("payments:simulate", args=[payment.pk]), {"action": "fail"})
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)


class QRGatingTests(PaymentTestBase):
    def test_qr_hidden_until_paid(self):
        self.client.force_login(self.user)
        url = reverse("reservations:detail", args=[self.reservation.pk])
        before = self.client.get(url)
        self.assertContains(before, "Pay now")
        self.assertNotContains(before, reverse("reservations:qr", args=[self.reservation.pk]))

        mark_paid(get_or_create_payment(self.reservation), method="gcash")
        after = self.client.get(url)
        self.assertContains(after, reverse("reservations:qr", args=[self.reservation.pk]))


class ReceiptAccessTests(PaymentTestBase):
    def test_other_user_cannot_view_receipt(self):
        mark_paid(get_or_create_payment(self.reservation), method="gcash")
        payment = Payment.objects.get(reservation=self.reservation)
        other = User.objects.create_user(
            username="other", email="other@e.com", password=PW, role=Roles.STUDENT
        )
        self.client.force_login(other)
        resp = self.client.get(reverse("payments:receipt", args=[payment.pk]))
        self.assertEqual(resp.status_code, 403)


class WebhookTests(PaymentTestBase):
    def _event(self, event_type):
        return {
            "data": {
                "attributes": {
                    "type": event_type,
                    "data": {
                        "id": "cs_test_123",
                        "attributes": {
                            "reference_number": self.reservation.code,
                            "payments": [{"attributes": {"source": {"type": "gcash"}}}],
                        },
                    },
                }
            }
        }

    def test_webhook_paid_marks_payment_and_is_idempotent(self):
        get_or_create_payment(self.reservation)  # PENDING
        payload = json.dumps(self._event("checkout_session.payment.paid"))
        for _ in range(2):  # duplicate delivery
            resp = self.client.post(
                reverse("payments:webhook"), payload, content_type="application/json"
            )
            self.assertEqual(resp.status_code, 200)
        payment = Payment.objects.get(reservation=self.reservation)
        self.assertEqual(payment.status, PaymentStatus.PAID)
        self.assertEqual(payment.method, "gcash")
        self.assertEqual(BillingRecord.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_webhook_unknown_reference_ignored(self):
        payload = json.dumps(
            {"data": {"attributes": {"type": "checkout_session.payment.paid",
                                      "data": {"id": "cs_x", "attributes": {"reference_number": "PUP-NOPE"}}}}}
        )
        resp = self.client.post(
            reverse("payments:webhook"), payload, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)  # ignored, not an error
