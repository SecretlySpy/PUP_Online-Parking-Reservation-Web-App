"""Capture one facility occupancy + revenue snapshot for trend charts.

Run on a schedule (e.g. every 15 minutes) alongside ``process_reservations``:

    python manage.py capture_occupancy_snapshot
"""

from django.core.management.base import BaseCommand

from dashboard.services import payment_stats, slot_stats
from parking.models import OccupancySnapshot


class Command(BaseCommand):
    help = "Record a point-in-time occupancy/revenue snapshot."

    def handle(self, *args, **options):
        slots = slot_stats()
        payments = payment_stats()
        snapshot = OccupancySnapshot.objects.create(
            total=slots["total"],
            available=slots["available_now"],
            occupied=slots["occupied_now"],
            maintenance=slots["maintenance"],
            paid_revenue_cents=payments["revenue_cents"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Captured snapshot at {snapshot.captured_at:%Y-%m-%d %H:%M} "
                f"(occupied={snapshot.occupied}/{snapshot.total})."
            )
        )
