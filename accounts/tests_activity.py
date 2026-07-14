"""Customer activity feed shows own + received events, scoped to the user."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.models import log_activity

User = get_user_model()
PW = "Str0ngPass!23"


class ActivityFeedTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="feeduser", email="feed@e.com", password=PW, role=Roles.STUDENT
        )
        self.admin = User.objects.create_user(
            username="feedadmin", email="feedadm@e.com", password=PW,
            role=Roles.ADMIN, is_staff=True,
        )
        # A self action (actor == customer) and an admin action targeting them.
        log_activity("reservation.created", "PUP-SELF01", actor=self.customer)
        log_activity(
            "reservation.status_set", "PUP-ADMN01", actor=self.admin, target_user=self.customer
        )
        # An unrelated event that must not appear in this customer's feed.
        log_activity("slot.created", "OTHERSLOT", actor=self.admin)

    def test_feed_shows_own_and_received_events_only(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("accounts:activity"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "PUP-SELF01")
        self.assertContains(resp, "PUP-ADMN01")
        self.assertNotContains(resp, "OTHERSLOT")
