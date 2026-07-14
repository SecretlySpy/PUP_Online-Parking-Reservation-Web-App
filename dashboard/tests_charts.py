"""Occupancy snapshot capture + reports charts."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.constants import VehicleType
from parking.models import Floor, OccupancySnapshot, Slot

from . import services

User = get_user_model()
PW = "Str0ngPass!23"


class OccupancyChartsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="chartadmin", email="chart@e.com", password=PW,
            role=Roles.ADMIN, is_staff=True,
        )
        floor = Floor.objects.create(name="Ch", code="CH", sort_order=93)
        Slot.objects.create(floor=floor, code="CH-01", slot_type=VehicleType.CAR)
        self.client.force_login(self.admin)

    def test_capture_command_creates_snapshot(self):
        call_command("capture_occupancy_snapshot")
        self.assertEqual(OccupancySnapshot.objects.count(), 1)
        snap = OccupancySnapshot.objects.get()
        self.assertEqual(snap.total, 1)

    def test_occupancy_series_returns_snapshots(self):
        call_command("capture_occupancy_snapshot")
        series = services.occupancy_series(hours=48)
        self.assertEqual(len(series), 1)
        self.assertIn("occupied", series[0])

    def test_reports_empty_state_without_snapshots(self):
        resp = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No snapshots yet")
        # The status-mix bar chart is always rendered.
        self.assertContains(resp, "Reservation status mix")
        self.assertContains(resp, "<svg")

    def test_reports_renders_occupancy_chart_with_snapshots(self):
        call_command("capture_occupancy_snapshot")
        resp = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Occupancy trend")
        self.assertNotContains(resp, "No snapshots yet")
        self.assertContains(resp, "polyline")  # the occupancy line chart
