from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Roles, Vehicle

User = get_user_model()

STRONG_PW = "Str0ngPass!23"


def customer_payload(**overrides):
    data = {
        "username": "juan",
        "role": Roles.STUDENT.value,
        "first_name": "Juan",
        "middle_name": "Dela",
        "last_name": "Cruz",
        "email": "juan@example.com",
        "id_number": "2021-00001",
        "contact_number": "09171234567",
        "address": "Sta. Mesa, Manila",
        "password1": STRONG_PW,
        "password2": STRONG_PW,
    }
    data.update(overrides)
    return data


class HomeTests(TestCase):
    def test_landing_page_renders(self):
        resp = self.client.get(reverse("core:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "parking slot")


class RegistrationTests(TestCase):
    def test_customer_registration_hashes_password_with_pbkdf2(self):
        resp = self.client.post(reverse("accounts:register"), customer_payload())
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username="juan")
        self.assertEqual(user.role, Roles.STUDENT)
        # Spec requirement: PBKDF2 password hashing.
        self.assertTrue(user.password.startswith("pbkdf2_"))
        self.assertTrue(user.check_password(STRONG_PW))
        # Registration signs the user in.
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_customer_cannot_self_assign_admin_role(self):
        resp = self.client.post(
            reverse("accounts:register"),
            customer_payload(role=Roles.ADMIN.value),
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_admin_registration_sets_admin_role_and_staff(self):
        resp = self.client.post(
            reverse("accounts:register_admin"),
            {
                "username": "boss",
                "first_name": "Ada",
                "last_name": "Admin",
                "email": "ada@example.com",
                "password1": STRONG_PW,
                "password2": STRONG_PW,
                "access_code": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        admin = User.objects.get(username="boss")
        self.assertEqual(admin.role, Roles.ADMIN)
        self.assertTrue(admin.is_staff)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="juan", email="juan@example.com", password=STRONG_PW
        )

    def test_reset_sends_one_time_email_link(self):
        resp = self.client.post(
            reverse("accounts:password_reset"), {"email": "juan@example.com"}
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)


class VehicleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="juan",
            email="juan@example.com",
            password=STRONG_PW,
            role=Roles.STUDENT,
        )
        self.client.force_login(self.user)

    def test_customer_can_add_vehicle(self):
        resp = self.client.post(
            reverse("accounts:vehicle_add"),
            {
                "plate_number": "abc123",
                "vehicle_type": "CAR",
                "make": "Toyota",
                "model": "Vios",
                "color": "White",
            },
        )
        self.assertRedirects(resp, reverse("accounts:vehicles"))
        vehicle = Vehicle.objects.get(owner=self.user)
        self.assertEqual(vehicle.plate_number, "ABC123")  # normalised upper-case
