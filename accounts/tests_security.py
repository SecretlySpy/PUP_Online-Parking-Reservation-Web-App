"""Login rate-limiting and email-verification tests."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from accounts.verification import make_email_token
from core.constants import VehicleType
from parking.models import Floor, Slot

User = get_user_model()
PW = "Str0ngPass!23"


@override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_ATTEMPT_WINDOW_MINUTES=15)
class LoginThrottleTests(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="victim", email="victim@e.com", password=PW, role=Roles.STUDENT
        )

    def test_blocks_after_max_failed_attempts(self):
        url = reverse("accounts:login")
        for _ in range(3):
            resp = self.client.post(url, {"username": "victim", "password": "wrong"})
            self.assertEqual(resp.status_code, 200)  # invalid form, re-rendered
        # The next attempt is throttled.
        blocked = self.client.post(url, {"username": "victim", "password": "wrong"})
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many failed sign-in", status_code=429)


class EmailVerificationTests(TestCase):
    def setUp(self):
        floor = Floor.objects.create(name="V", code="VF", sort_order=94)
        self.slot = Slot.objects.create(floor=floor, code="VF-01", slot_type=VehicleType.CAR)
        self.user = User.objects.create_user(
            username="unverified", email="unv@e.com", password=PW, role=Roles.STUDENT
        )
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified"])
        self.client.force_login(self.user)

    def test_unverified_customer_is_gated_from_booking(self):
        resp = self.client.get(reverse("reservations:create", args=[self.slot.pk]))
        self.assertRedirects(resp, reverse("accounts:verify_notice"))

    def test_valid_token_verifies_and_unlocks_booking(self):
        token = make_email_token(self.user)
        resp = self.client.get(reverse("accounts:verify_email", args=[token]))
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        # Booking is now reachable (renders the form).
        booking = self.client.get(reverse("reservations:create", args=[self.slot.pk]))
        self.assertEqual(booking.status_code, 200)

    def test_invalid_token_redirects_to_notice(self):
        resp = self.client.get(reverse("accounts:verify_email", args=["not-a-valid-token"]))
        self.assertRedirects(resp, reverse("accounts:verify_notice"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
