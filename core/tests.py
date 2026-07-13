from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles

from .models import ActivityLog, log_activity

User = get_user_model()


class ActivityLogTests(TestCase):
    def test_log_activity_persists_actor_and_request_ip(self):
        actor = User.objects.create_user(
            username="audited",
            email="audited@example.com",
            password="Str0ngPass!23",
            role=Roles.STUDENT,
        )
        request = type(
            "RequestStub",
            (),
            {"user": actor, "client_ip": "127.0.0.1"},
        )()
        entry = log_activity("test.event", "evidence", request=request)
        self.assertEqual(entry.actor, actor)
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_custom_403_template_is_used(self):
        customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="Str0ngPass!23",
            role=Roles.STUDENT,
        )
        self.client.force_login(customer)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Access denied", status_code=403)
