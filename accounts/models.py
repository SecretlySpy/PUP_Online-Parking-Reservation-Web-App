from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from core.constants import VehicleType


class Roles(models.TextChoices):
    STUDENT = "STUDENT", "Student"
    EMPLOYEE = "EMPLOYEE", "Employee"
    VISITOR = "VISITOR", "Visitor"
    ADMIN = "ADMIN", "Administrator"


#: Roles that represent parking customers (as opposed to administrators).
CUSTOMER_ROLES = (Roles.STUDENT, Roles.EMPLOYEE, Roles.VISITOR)


class CustomUserManager(UserManager):
    """Ensure superusers created via ``createsuperuser`` get the ADMIN role."""

    def create_superuser(self, username, email=None, password=None, **extra):
        extra.setdefault("role", Roles.ADMIN)
        return super().create_superuser(username, email, password, **extra)


class User(AbstractUser):
    """Account for every actor in the system.

    A single user table with a ``role`` field backs role-based access for
    students, employees, visitors, and administrators. Email is unique because
    the password-reset workflow is email-addressed.
    """

    role = models.CharField(
        max_length=16, choices=Roles.choices, default=Roles.VISITOR
    )
    middle_name = models.CharField(max_length=150, blank=True)
    # e.g. student/employee number; blank for visitors.
    id_number = models.CharField("ID number", max_length=32, blank=True)
    contact_number = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    email = models.EmailField("email address", unique=True)
    # Defaults True so existing/admin/programmatic accounts are unaffected; the
    # customer self-registration flow sets it False and gates booking until the
    # emailed verification link is followed.
    email_verified = models.BooleanField(default=True)

    objects = CustomUserManager()

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        full = self.get_full_name()
        return full or self.username

    @property
    def is_admin_role(self):
        return self.role == Roles.ADMIN or self.is_staff

    @property
    def is_customer_role(self):
        return self.role in CUSTOMER_ROLES

    def get_full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p).strip()


class Vehicle(models.Model):
    """A vehicle belonging to a customer; selected when booking a slot."""

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="vehicles"
    )
    plate_number = models.CharField(max_length=16)
    vehicle_type = models.CharField(
        max_length=16, choices=VehicleType.choices, default=VehicleType.CAR
    )
    make = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=64, blank=True)
    color = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["plate_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "plate_number"],
                name="unique_plate_per_owner",
            )
        ]

    def __str__(self):
        return f"{self.plate_number} ({self.get_vehicle_type_display()})"

    @property
    def label(self):
        bits = [self.make, self.model]
        desc = " ".join(b for b in bits if b)
        return f"{self.plate_number} — {desc}" if desc else self.plate_number
