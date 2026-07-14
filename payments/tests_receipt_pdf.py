"""PDF receipt download: owner/admin-scoped and paid-only."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.constants import VehicleType
from parking.models import Floor, Slot
from reservations.models import Reservation

from .models import Payment, PaymentStatus

User = get_user_model()
PW = "Str0ngPass!23"


class ReceiptPdfDownloadTests(TestCase):
    def setUp(self):
        floor = Floor.objects.create(name="R", code="RC", sort_order=97)
        slot = Slot.objects.create(floor=floor, code="RC-01", slot_type=VehicleType.CAR)
        self.owner = User.objects.create_user(
            username="pdf-owner", email="pdfo@e.com", password=PW, role=Roles.STUDENT
        )
        self.other = User.objects.create_user(
            username="pdf-other", email="pdfx@e.com", password=PW, role=Roles.STUDENT
        )
        start = timezone.now() + timedelta(hours=2)
        self.res = Reservation.objects.create(
            customer=self.owner, slot=slot, start_at=start, end_at=start + timedelta(hours=1)
        )
        self.payment = Payment.objects.create(
            reservation=self.res, amount_cents=5000, reference=self.res.code,
            status=PaymentStatus.PAID, paid_at=timezone.now(),
        )

    def test_owner_downloads_pdf(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("payments:receipt_pdf", args=[self.payment.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(resp.content[:4], b"%PDF")

    def test_other_customer_denied_pdf(self):
        self.client.force_login(self.other)
        resp = self.client.get(reverse("payments:receipt_pdf", args=[self.payment.pk]))
        self.assertEqual(resp.status_code, 403)
