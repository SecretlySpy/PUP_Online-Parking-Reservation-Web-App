from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles, Vehicle
from core.constants import VehicleType
from parking.models import Floor, Slot, SlotStatus
from parking.services import slots_with_availability
from payments.models import Payment, PaymentStatus

from .models import Reservation, ReservationStatus
from .utils import sign_reservation, unsign_token

User = get_user_model()
PW = "Str0ngPass!23"


def make_customer(username="cust"):
    return User.objects.create_user(
        username=username, email=f"{username}@e.com", password=PW, role=Roles.STUDENT
    )


class ReservationModelTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.user = make_customer()

    def _mk(self, offset_hours=1, dur_hours=1, status=ReservationStatus.RESERVED):
        start = timezone.now() + timedelta(hours=offset_hours)
        return Reservation.objects.create(
            customer=self.user, slot=self.slot,
            start_at=start, end_at=start + timedelta(hours=dur_hours), status=status,
        )

    def test_code_and_fee_assigned_on_create(self):
        r = self._mk()
        self.assertTrue(r.code.startswith("PUP-"))
        self.assertGreater(r.fee_cents, 0)

    def test_signed_qr_token_roundtrips_and_rejects_tampering(self):
        r = self._mk()
        token = sign_reservation(r)
        self.assertEqual(unsign_token(token)["id"], r.pk)
        self.assertIsNone(unsign_token(token + "x"))  # tampered → None

    def test_active_reservation_blocks_slot_availability(self):
        start = timezone.now() + timedelta(hours=2)
        self._mk(offset_hours=2)
        _, summary = slots_with_availability(
            start=start, end=start + timedelta(minutes=30)
        )
        self.assertEqual(summary["available"], 0)  # overlapping window

    def test_overlapping_detects_conflict(self):
        r = self._mk(offset_hours=3)
        conflict = Reservation.overlapping(
            self.slot, r.start_at, r.end_at
        )
        self.assertTrue(conflict.exists())

    def test_database_rejects_non_positive_reservation_window(self):
        start = timezone.now() + timedelta(hours=1)

        # The database constraint is the final integrity boundary when a caller
        # bypasses the form and service validation layers.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reservation.objects.create(
                customer=self.user,
                slot=self.slot,
                start_at=start,
                end_at=start,
            )


class BookingFlowTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.user = make_customer()
        self.vehicle = Vehicle.objects.create(
            owner=self.user, plate_number="ABC123", vehicle_type=VehicleType.CAR
        )
        self.client.force_login(self.user)

    def _payload(self):
        # Use a fixed daytime window TOMORROW in the project's local timezone so
        # the booking is always in the future and never crosses midnight — the
        # form interprets the naive date/time in Asia/Manila (settings TZ).
        tomorrow = (timezone.localtime(timezone.now()) + timedelta(days=1)).date()
        return {
            "vehicle": self.vehicle.pk,
            "date": tomorrow.isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
        }

    def test_customer_can_book_slot(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                reverse("reservations:create", args=[self.slot.pk]), self._payload()
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Reservation.objects.filter(customer=self.user).count(), 1)
        self.assertTrue(
            Payment.objects.filter(
                reservation__customer=self.user,
                status=PaymentStatus.PENDING,
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("complete payment", mail.outbox[0].body.lower())

    def test_vehicle_type_must_match_slot(self):
        self.vehicle.vehicle_type = VehicleType.MOTORCYCLE
        self.vehicle.save(update_fields=["vehicle_type"])
        response = self.client.post(
            reverse("reservations:create", args=[self.slot.pk]),
            self._payload(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not match")
        self.assertFalse(Reservation.objects.exists())

    def test_double_booking_rejected(self):
        # First booking succeeds.
        self.client.post(reverse("reservations:create", args=[self.slot.pk]), self._payload())
        # Overlapping booking is rejected (form re-rendered, no new row).
        resp = self.client.post(
            reverse("reservations:create", args=[self.slot.pk]), self._payload()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "overlapping")
        self.assertEqual(Reservation.objects.count(), 1)

    def test_cancel_frees_the_slot(self):
        self.client.post(reverse("reservations:create", args=[self.slot.pk]), self._payload())
        r = Reservation.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("reservations:cancel", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, ReservationStatus.CANCELLED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("cancelled", mail.outbox[0].subject.lower())

    def test_detail_and_history_pages_render(self):
        self.client.post(reverse("reservations:create", args=[self.slot.pk]), self._payload())
        r = Reservation.objects.get()
        detail = self.client.get(reverse("reservations:detail", args=[r.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, r.code)
        # Unpaid: QR is gated behind payment, so the Pay CTA is shown instead.
        # (QR-after-payment is covered by payments.QRGatingTests.)
        self.assertContains(detail, "Pay now")
        history = self.client.get(reverse("reservations:history"))
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, r.code)


class AccessControlTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.owner = make_customer("owner")
        self.other = make_customer("other")
        start = timezone.now() + timedelta(hours=1)
        self.res = Reservation.objects.create(
            customer=self.owner, slot=self.slot,
            start_at=start, end_at=start + timedelta(hours=1),
        )

    def test_other_customer_cannot_view_reservation(self):
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("reservations:detail", args=[self.res.pk])).status_code,
            403,
        )

    def test_other_customer_cannot_cancel_reservation(self):
        self.client.force_login(self.other)
        # get_object_or_404(..., customer=request.user) → 404 for non-owner.
        self.assertEqual(
            self.client.post(reverse("reservations:cancel", args=[self.res.pk])).status_code,
            404,
        )


class VerificationTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="G", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.customer = make_customer()
        self.admin = User.objects.create_user(
            username="adm", email="adm@e.com", password=PW, role=Roles.ADMIN, is_staff=True
        )
        # A five-minute lead is inside the configured early-arrival grace.
        start = timezone.now() + timedelta(minutes=5)
        self.res = Reservation.objects.create(
            customer=self.customer, slot=self.slot,
            start_at=start, end_at=start + timedelta(hours=1),
        )
        self.payment = Payment.objects.create(
            reservation=self.res,
            amount_cents=self.res.fee_cents,
            reference=self.res.code,
            status=PaymentStatus.PAID,
            paid_at=timezone.now(),
        )

    def test_staff_verify_marks_occupied(self):
        self.client.force_login(self.admin)
        token = sign_reservation(self.res)
        resp = self.client.post(reverse("reservations:verify"), {"t": token})
        self.assertEqual(resp.status_code, 302)
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, ReservationStatus.OCCUPIED)

    def test_verify_page_renders_for_staff(self):
        self.client.force_login(self.admin)
        token = sign_reservation(self.res)
        resp = self.client.get(reverse("reservations:verify"), {"t": token})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.res.code)

    def test_qr_image_owner_only(self):
        # Anonymous cannot fetch someone's QR.
        resp = self.client.get(reverse("reservations:qr", args=[self.res.pk]))
        self.assertEqual(resp.status_code, 403)
        # Owner can, and gets a PNG.
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("reservations:qr", args=[self.res.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")

    def test_unpaid_owner_cannot_fetch_qr_or_check_in(self):
        self.payment.status = PaymentStatus.PENDING
        self.payment.paid_at = None
        self.payment.save(update_fields=["status", "paid_at"])
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(reverse("reservations:qr", args=[self.res.pk])).status_code,
            403,
        )

        self.client.force_login(self.admin)
        token = sign_reservation(self.res)
        self.client.post(reverse("reservations:verify"), {"t": token})
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, ReservationStatus.RESERVED)

    def test_paid_reservation_cannot_check_in_too_early(self):
        self.res.start_at = timezone.now() + timedelta(hours=2)
        self.res.end_at = self.res.start_at + timedelta(hours=1)
        self.res.save(update_fields=["start_at", "end_at"])
        self.client.force_login(self.admin)
        token = sign_reservation(self.res)
        response = self.client.post(
            reverse("reservations:verify"),
            {"t": token},
            follow=True,
        )
        self.res.refresh_from_db()
        self.assertEqual(self.res.status, ReservationStatus.RESERVED)
        self.assertContains(response, "not yet within")
