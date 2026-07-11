from django.db import models


class VehicleType(models.TextChoices):
    """Shared vehicle/slot categories used for matching a vehicle to a slot."""

    MOTORCYCLE = "MOTORCYCLE", "Motorcycle"
    CAR = "CAR", "Car"
    SUV = "SUV", "SUV"
    VAN = "VAN", "Van"
    TRUCK = "TRUCK", "Truck"
