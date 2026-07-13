import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles, Vehicle
from core.constants import VehicleType
from parking.models import Floor, Slot
from reservations.models import Reservation, ReservationStatus

from . import gateway
from .models import (
    BillingRecord,
    PayMongoWebhookEvent,
    Payment,
    PaymentStatus,
    WebhookOutcome,
)
from .services import (
    get_or_create_payment,
    mark_failed,
    mark_paid,
    prepare_payment,
)

User = get_user_model()
PW = "Str0ngPass!23"


class PaymentTestBase(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(
            floor=self.floor,
            code="G-01",
            slot_type=VehicleType.CAR,
        )
        self.user = User.objects.create_user(
            username="cust",
            email="cust@e.com",
            password=PW,
            role=Roles.STUDENT,
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.user,
            plate_number="ABC123",
            vehicle_type=VehicleType.CAR,
        )
        start = timezone.now() + timedelta(hours=2)
        self.reservation = Reservation.objects.create(
            customer=self.user,
            slot=self.slot,
            vehicle=self.vehicle,
            start_at=start,
            end_at=start + timedelta(hours=1),
        )


class PaymentServiceTests(PaymentTestBase):
    def test_get_or_create_uses_reservation_fee_and_code(self):
        payment = get_or_create_payment(self.reservation)
        self.assertEqual(payment.amount_cents, self.reservation.fee_cents)
        self.assertEqual(payment.reference, self.reservation.code)
        # Idempotent — same row and provider key are returned.
        same_payment = get_or_create_payment(self.reservation)
        self.assertEqual(same_payment.pk, payment.pk)
        self.assertEqual(
            same_payment.checkout_idempotency_key,
            payment.checkout_idempotency_key,
        )

    def test_pending_retry_keeps_key_but_failed_retry_rotates_gateway_identity(self):
        payment = get_or_create_payment(self.reservation)
        original_key = payment.checkout_idempotency_key

        first_pending = prepare_payment(self.reservation)
        second_pending = prepare_payment(self.reservation)
        self.assertEqual(first_pending.checkout_idempotency_key, original_key)
        self.assertEqual(second_pending.checkout_idempotency_key, original_key)

        payment.checkout_session_id = "cs_failed_attempt"
        payment.payment_intent_id = "pi_failed_attempt"
        payment.save(update_fields=["checkout_session_id", "payment_intent_id"])
        mark_failed(payment)

        reopened = prepare_payment(self.reservation)
        self.assertEqual(reopened.status, PaymentStatus.PENDING)
        self.assertNotEqual(reopened.checkout_idempotency_key, original_key)
        self.assertEqual(reopened.checkout_session_id, "")
        self.assertEqual(reopened.payment_intent_id, "")

    def test_mark_paid_issues_billing_and_email_once(self):
        payment = get_or_create_payment(self.reservation)
        # Production sends only after commit; execute captured callbacks inside
        # TestCase's wrapping transaction to assert observable delivery.
        with self.captureOnCommitCallbacks(execute=True):
            mark_paid(payment, method="gcash")
            mark_paid(payment, method="gcash")  # duplicate gateway retry
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.PAID)
        self.assertEqual(BillingRecord.objects.filter(payment=payment).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.reservation.code, mail.outbox[0].body)


class PayMongoGatewayTests(PaymentTestBase):
    @override_settings(PAYMONGO_SECRET_KEY="sk_test_configured")
    @patch("payments.gateway.requests.post")
    def test_checkout_creation_reuses_persisted_idempotency_key(self, post):
        payment = get_or_create_payment(self.reservation)
        response = Mock()
        response.json.return_value = {
            "data": {
                "id": "cs_test_123",
                "attributes": {"checkout_url": "https://checkout.example/session"},
            }
        }
        post.return_value = response

        for _ in range(2):
            gateway.create_checkout_session(
                payment,
                "https://parking.example/success",
                "https://parking.example/cancel",
            )

        keys = [
            call.kwargs["headers"]["Idempotency-Key"]
            for call in post.call_args_list
        ]
        self.assertEqual(keys, [str(payment.checkout_idempotency_key)] * 2)


class SimulatedCheckoutTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_start_rejects_get_without_creating_payment(self):
        response = self.client.get(
            reverse("payments:start", args=[self.reservation.pk])
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Payment.objects.filter(reservation=self.reservation).exists())

    def test_start_post_redirects_to_simulator_when_unconfigured(self):
        response = self.client.post(
            reverse("payments:start", args=[self.reservation.pk])
        )
        payment = Payment.objects.get(reservation=self.reservation)
        self.assertRedirects(
            response,
            reverse("payments:simulate", args=[payment.pk]),
        )

    def test_simulated_success_marks_paid_and_shows_receipt(self):
        self.client.post(reverse("payments:start", args=[self.reservation.pk]))
        payment = Payment.objects.get(reservation=self.reservation)
        response = self.client.post(
            reverse("payments:simulate", args=[payment.pk]),
            {"action": "success"},
        )
        self.assertRedirects(
            response,
            reverse("payments:receipt", args=[payment.pk]),
        )
        payment.refresh_from_db()
        self.assertTrue(payment.is_paid)

    def test_simulated_failure_marks_failed(self):
        self.client.post(reverse("payments:start", args=[self.reservation.pk]))
        payment = Payment.objects.get(reservation=self.reservation)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("payments:simulate", args=[payment.pk]),
                {"action": "fail"},
            )
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            reverse("reservations:detail", args=[self.reservation.pk]),
            mail.outbox[0].body,
        )
        self.assertNotIn(
            reverse("payments:start", args=[self.reservation.pk]),
            mail.outbox[0].body,
        )

    def test_cancelled_reservation_cannot_start_payment(self):
        self.reservation.status = ReservationStatus.CANCELLED
        self.reservation.save(update_fields=["status"])
        response = self.client.post(
            reverse("payments:start", args=[self.reservation.pk]),
            follow=True,
        )
        self.assertContains(response, "Only an active reserved booking")
        self.assertFalse(Payment.objects.filter(reservation=self.reservation).exists())


class QRGatingTests(PaymentTestBase):
    def test_qr_hidden_until_paid(self):
        self.client.force_login(self.user)
        url = reverse("reservations:detail", args=[self.reservation.pk])
        before = self.client.get(url)
        self.assertContains(before, "Pay now")
        self.assertContains(before, 'method="post"')
        self.assertNotContains(
            before,
            reverse("reservations:qr", args=[self.reservation.pk]),
        )
        self.assertEqual(
            self.client.get(
                reverse("reservations:qr", args=[self.reservation.pk])
            ).status_code,
            403,
        )

        mark_paid(get_or_create_payment(self.reservation), method="gcash")
        after = self.client.get(url)
        self.assertContains(
            after,
            reverse("reservations:qr", args=[self.reservation.pk]),
        )


class ReceiptAccessTests(PaymentTestBase):
    def test_other_user_cannot_view_receipt(self):
        mark_paid(get_or_create_payment(self.reservation), method="gcash")
        payment = Payment.objects.get(reservation=self.reservation)
        other = User.objects.create_user(
            username="other",
            email="other@e.com",
            password=PW,
            role=Roles.STUDENT,
        )
        self.client.force_login(other)
        response = self.client.get(reverse("payments:receipt", args=[payment.pk]))
        self.assertEqual(response.status_code, 403)


class WebhookTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.payment = get_or_create_payment(self.reservation)
        self.payment.checkout_session_id = "cs_test_123"
        self.payment.save(update_fields=["checkout_session_id"])

    def _event(
        self,
        *,
        event_id="evt_test_123",
        event_type="checkout_session.payment.paid",
        session_id="cs_test_123",
        livemode=False,
        reference=None,
        amount=None,
        currency=None,
        payment_status="paid",
    ):
        return {
            "data": {
                "id": event_id,
                "attributes": {
                    "type": event_type,
                    "livemode": livemode,
                    "data": {
                        "id": session_id,
                        "type": "checkout_session",
                        "attributes": {
                            "reference_number": reference or self.payment.reference,
                            "payment_intent": {"id": "pi_test_123"},
                            "payments": [
                                {
                                    "id": "pay_test_123",
                                    "attributes": {
                                        "amount": (
                                            self.payment.amount_cents
                                            if amount is None
                                            else amount
                                        ),
                                        "currency": currency or self.payment.currency,
                                        "status": payment_status,
                                        "source": {"type": "gcash"},
                                    },
                                }
                            ],
                        },
                    },
                },
            }
        }

    def _post_event(self, event):
        return self.client.post(
            reverse("payments:webhook"),
            json.dumps(event),
            content_type="application/json",
        )

    def test_webhook_paid_marks_payment_and_deduplicates_provider_event(self):
        event = self._event()
        with self.captureOnCommitCallbacks(execute=True):
            first = self._post_event(event)
            duplicate = self._post_event(event)

        self.assertEqual(first.status_code, 200)
        self.assertJSONEqual(first.content, {"status": "processed"})
        self.assertJSONEqual(duplicate.content, {"status": "duplicate"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PAID)
        self.assertEqual(self.payment.method, "gcash")
        self.assertEqual(self.payment.payment_intent_id, "pi_test_123")
        self.assertEqual(BillingRecord.objects.count(), 1)
        self.assertEqual(PayMongoWebhookEvent.objects.count(), 1)
        self.assertEqual(
            PayMongoWebhookEvent.objects.get().outcome,
            WebhookOutcome.PROCESSED,
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_webhook_rejects_mode_reference_amount_and_currency_mismatches(self):
        cases = [
            (
                "evt_live",
                {"livemode": True},
                "event mode does not match gateway configuration",
            ),
            (
                "evt_reference",
                {"reference": "PUP-WRONG"},
                "checkout reference mismatch",
            ),
            (
                "evt_amount",
                {"amount": self.payment.amount_cents + 1},
                "checkout amount mismatch",
            ),
            (
                "evt_currency",
                {"currency": "USD"},
                "checkout currency mismatch",
            ),
        ]
        for event_id, overrides, expected_detail in cases:
            with self.subTest(event_id=event_id):
                response = self._post_event(
                    self._event(event_id=event_id, **overrides)
                )
                self.assertEqual(response.status_code, 200)
                delivery = PayMongoWebhookEvent.objects.get(event_id=event_id)
                self.assertEqual(delivery.outcome, WebhookOutcome.REJECTED)
                self.assertEqual(delivery.detail, expected_detail)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)
        self.assertFalse(BillingRecord.objects.exists())

    def test_webhook_requires_exact_unambiguous_checkout_session(self):
        unknown = self._post_event(
            self._event(event_id="evt_unknown", session_id="cs_unknown")
        )
        self.assertJSONEqual(unknown.content, {"status": "rejected"})
        self.assertEqual(
            PayMongoWebhookEvent.objects.get(event_id="evt_unknown").detail,
            "unknown checkout session",
        )

        other_slot = Slot.objects.create(
            floor=self.floor,
            code="G-02",
            slot_type=VehicleType.CAR,
        )
        other_reservation = Reservation.objects.create(
            customer=self.user,
            slot=other_slot,
            vehicle=self.vehicle,
            start_at=self.reservation.start_at,
            end_at=self.reservation.end_at,
        )
        Payment.objects.create(
            reservation=other_reservation,
            amount_cents=other_reservation.fee_cents,
            reference=other_reservation.code,
            checkout_session_id=self.payment.checkout_session_id,
        )
        ambiguous = self._post_event(self._event(event_id="evt_ambiguous"))
        self.assertJSONEqual(ambiguous.content, {"status": "rejected"})
        self.assertEqual(
            PayMongoWebhookEvent.objects.get(event_id="evt_ambiguous").detail,
            "ambiguous checkout session",
        )

    def test_webhook_ignores_unsubscribed_event_type_with_audit_record(self):
        response = self._post_event(
            self._event(
                event_id="evt_unexpected",
                event_type="link.payment.paid",
            )
        )
        self.assertJSONEqual(response.content, {"status": "ignored"})
        delivery = PayMongoWebhookEvent.objects.get(event_id="evt_unexpected")
        self.assertEqual(delivery.outcome, WebhookOutcome.IGNORED)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)
