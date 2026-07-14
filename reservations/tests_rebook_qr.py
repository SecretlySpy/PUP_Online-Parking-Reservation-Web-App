"""Quick re-book prefill and QR attachment download."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles, Vehicle
from core.constants import VehicleType
from parking.models import Floor, Slot
from payments.models import Payment, PaymentStatus

from .models import Reservation

User = get_user_model()
PW = "Str0ngPass!23"


class QuickRebookAndQrDownloadTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="Q", code="QB", sort_order=96)
        self.slot = Slot.objects.create(floor=self.floor, code="QB-01", slot_type=VehicleType.CAR)
        self.user = User.objects.create_user(
            username="rebook", email="rebook@e.com", password=PW, role=Roles.STUDENT
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.user, plate_number="RBK123", vehicle_type=VehicleType.CAR
        )
        self.client.force_login(self.user)

    def test_create_prefills_vehicle_from_querystring(self):
        resp = self.client.get(
            reverse("reservations:create", args=[self.slot.pk]),
            {"vehicle": str(self.vehicle.pk)},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial.get("vehicle"), str(self.vehicle.pk))

    def test_qr_download_sets_attachment_header(self):
        start = timezone.now() + timedelta(hours=1)
        res = Reservation.objects.create(
            customer=self.user, slot=self.slot, vehicle=self.vehicle,
            start_at=start, end_at=start + timedelta(hours=1),
        )
        Payment.objects.create(
            reservation=res, amount_cents=5000, reference=res.code,
            status=PaymentStatus.PAID, paid_at=timezone.now(),
        )
        resp = self.client.get(reverse("reservations:qr", args=[res.pk]), {"download": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("attachment", resp["Content-Disposition"])
