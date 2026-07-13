from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.constants import VehicleType
from reservations.models import Reservation, ReservationStatus

from .models import Floor, Slot, SlotStatus
from .services import facility_floors, slots_with_availability

User = get_user_model()


class AvailabilityServiceTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="Ground", code="G", sort_order=1)
        self.open1 = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.open2 = Slot.objects.create(floor=self.floor, code="G-02", slot_type=VehicleType.CAR)
        self.maint = Slot.objects.create(
            floor=self.floor, code="G-03", slot_type=VehicleType.CAR,
            status=SlotStatus.MAINTENANCE,
        )

    def test_maintenance_slot_is_not_available(self):
        slots, summary = slots_with_availability()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["available"], 2)
        self.assertEqual(summary["maintenance"], 1)

    def test_only_available_filter_excludes_maintenance(self):
        slots, summary = slots_with_availability(only_available=True)
        codes = {s.code for s in slots}
        self.assertEqual(codes, {"G-01", "G-02"})

    def test_vehicle_type_filter(self):
        Slot.objects.create(floor=self.floor, code="G-04", slot_type=VehicleType.MOTORCYCLE)
        slots, _ = slots_with_availability(vehicle_type=VehicleType.MOTORCYCLE)
        self.assertEqual([s.code for s in slots], ["G-04"])

    def test_inactive_floor_hidden(self):
        self.floor.is_active = False
        self.floor.save()
        _, summary = slots_with_availability()
        self.assertEqual(summary["total"], 0)


class SlotViewTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="Ground", code="G", sort_order=1)
        Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)

    def test_slots_page_renders(self):
        resp = self.client.get(reverse("parking:slots"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Real-time parking availability")

    def test_slots_partial_renders_grid(self):
        resp = self.client.get(reverse("parking:slots_partial"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "G-01")

    def test_slots_api_returns_json(self):
        resp = self.client.get(reverse("parking:slots_api"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["summary"]["available"], 1)
        self.assertEqual(data["slots"][0]["code"], "G-01")

    def test_unfiltered_api_reports_current_reservation_as_unavailable(self):
        customer = User.objects.create_user(
            username="live-customer",
            email="live@example.com",
            password="Str0ngPass!23",
            role=Roles.STUDENT,
        )
        slot = Slot.objects.get(code="G-01")
        now = timezone.now()
        Reservation.objects.create(
            customer=customer,
            slot=slot,
            start_at=now - timedelta(minutes=5),
            end_at=now + timedelta(minutes=30),
            status=ReservationStatus.RESERVED,
        )
        payload = self.client.get(reverse("parking:slots_api")).json()
        self.assertEqual(payload["summary"]["available"], 0)
        self.assertFalse(payload["slots"][0]["available"])


class FacilityGuideTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(
            name="Ground", code="G", sort_order=1, image="img/areas/area-1.jpg"
        )
        Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        Slot.objects.create(
            floor=self.floor, code="G-02", slot_type=VehicleType.CAR,
            status=SlotStatus.MAINTENANCE,
        )

    def test_facility_floors_counts(self):
        rows = facility_floors()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 2)
        self.assertEqual(rows[0]["available"], 1)  # one maintenance excluded

    def test_facility_page_renders_with_photo(self):
        resp = self.client.get(reverse("parking:facility"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Parking facility guide")
        self.assertContains(resp, "img/areas/area-1.jpg")


class SeedCommandTests(TestCase):
    def test_seed_creates_floors_with_photos(self):
        call_command("seed_parking")
        floors = Floor.objects.all()
        self.assertEqual(floors.count(), 4)
        self.assertTrue(all(f.image for f in floors))  # every floor has a photo


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(TestCase):
    def test_custom_404_uses_parking_signal(self):
        resp = self.client.get("/no-such-page/")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Wrong turn", status_code=404)
        self.assertContains(resp, "parking-signal", status_code=404)


class AdminSlotManagementTests(TestCase):
    def setUp(self):
        self.floor = Floor.objects.create(name="Ground", code="G", sort_order=1)
        self.slot = Slot.objects.create(floor=self.floor, code="G-01", slot_type=VehicleType.CAR)
        self.admin = User.objects.create_user(
            username="admin1", email="a@e.com", password="Str0ngPass!23",
            role=Roles.ADMIN, is_staff=True,
        )
        self.customer = User.objects.create_user(
            username="cust1", email="c@e.com", password="Str0ngPass!23",
            role=Roles.STUDENT,
        )

    def test_admin_can_toggle_slot_to_maintenance(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("parking:slot_toggle", args=[self.slot.pk]))
        self.assertEqual(resp.status_code, 302)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, SlotStatus.MAINTENANCE)

    def test_customer_cannot_manage_slots(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("parking:slot_list"))
        self.assertEqual(resp.status_code, 403)
