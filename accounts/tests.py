from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
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

    @override_settings(ADMIN_SIGNUP_ENABLED=False, ADMIN_SIGNUP_CODE="")
    def test_admin_registration_is_hidden_when_not_explicitly_enabled(self):
        """The privileged registration route must fail closed by default."""
        resp = self.client.get(reverse("accounts:register_admin"))
        self.assertEqual(resp.status_code, 404)

    @override_settings(
        ADMIN_SIGNUP_ENABLED=True,
        ADMIN_SIGNUP_CODE="test-admin-signup-code-2026",
    )
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
                "access_code": "test-admin-signup-code-2026",
            },
        )
        self.assertEqual(resp.status_code, 302)
        admin = User.objects.get(username="boss")
        self.assertEqual(admin.role, Roles.ADMIN)
        self.assertTrue(admin.is_staff)

    @override_settings(ADMIN_SIGNUP_ENABLED=True, ADMIN_SIGNUP_CODE="")
    def test_admin_registration_rejects_missing_server_side_code(self):
        """Enabling the route alone cannot recreate the old open signup bug."""
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
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="boss").exists())
        self.assertContains(resp, "Incorrect administrator access code.")

    @override_settings(
        ADMIN_SIGNUP_ENABLED=True,
        ADMIN_SIGNUP_CODE="test-admin-signup-code-2026",
        ADMIN_SIGNUP_MAX_ATTEMPTS=2,
        ADMIN_SIGNUP_WINDOW_MINUTES=15,
    )
    def test_admin_registration_throttles_repeated_code_guesses(self):
        payload = {
            "username": "boss",
            "first_name": "Ada",
            "last_name": "Admin",
            "email": "ada@example.com",
            "password1": STRONG_PW,
            "password2": STRONG_PW,
            "access_code": "wrong-code",
        }

        self.assertEqual(
            self.client.post(reverse("accounts:register_admin"), payload).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(reverse("accounts:register_admin"), payload).status_code,
            200,
        )
        response = self.client.post(reverse("accounts:register_admin"), payload)

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many administrator enrollment attempts", status_code=429)
        self.assertFalse(User.objects.filter(username="boss").exists())


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
