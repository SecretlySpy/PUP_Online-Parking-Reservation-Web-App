"""Seed demo floors and slots so the app is explorable immediately.

Idempotent: re-running only fills gaps (uses get_or_create) and refreshes each
floor's photo, so it is safe to run repeatedly during development and demos.

    python manage.py seed_parking
"""

from django.core.management.base import BaseCommand

from core.constants import VehicleType
from parking.models import Floor, Slot, SlotStatus

# (name, code, sort_order, image, [(slot_type, count), ...]) — the demo facility.
# Photos are the repurposed legacy parking-area images now in static/img/areas/.
FLOOR_PLAN = [
    ("Ground Floor", "G", 1, "img/areas/area-1.jpg",
     [(VehicleType.MOTORCYCLE, 6), (VehicleType.CAR, 10)]),
    ("2nd Floor", "2F", 2, "img/areas/area-2.jpg",
     [(VehicleType.CAR, 12), (VehicleType.SUV, 4)]),
    ("3rd Floor", "3F", 3, "img/areas/area-3.jpg",
     [(VehicleType.CAR, 12), (VehicleType.VAN, 3)]),
    ("4th Floor", "4F", 4, "img/areas/area-4.jpg",
     [(VehicleType.CAR, 10), (VehicleType.MOTORCYCLE, 6)]),
]


class Command(BaseCommand):
    help = "Create demo parking floors and slots (idempotent)."

    def handle(self, *args, **options):
        created_slots = 0
        for name, code, order, image, groups in FLOOR_PLAN:
            floor, _ = Floor.objects.get_or_create(
                code=code, defaults={"name": name, "sort_order": order}
            )
            # Refresh photo/metadata each run so existing rows also get images.
            floor.name = name
            floor.sort_order = order
            floor.image = image
            floor.save(update_fields=["name", "sort_order", "image"])

            # Number slots per type sequentially within the floor, e.g. G-CAR-01.
            for slot_type, count in groups:
                for n in range(1, count + 1):
                    slot_code = f"{code}-{slot_type[:3]}-{n:02d}"
                    _, was_created = Slot.objects.get_or_create(
                        floor=floor,
                        code=slot_code,
                        defaults={
                            "slot_type": slot_type,
                            "status": SlotStatus.AVAILABLE,
                        },
                    )
                    created_slots += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Floor.objects.count()} floors; "
                f"added {created_slots} new slots "
                f"({Slot.objects.count()} total)."
            )
        )
