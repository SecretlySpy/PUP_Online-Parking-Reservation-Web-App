"""Targeted tests for automated reservation lifecycle processing."""

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Roles
from core.constants import VehicleType
from core.models import ActivityLog
from parking.models import Floor, Slot
from payments.models import Payment, PaymentStatus

from .lifecycle import process_reservation_lifecycle
from .models import Reservation, ReservationStatus


User = get_user_model()


class ReservationLifecycleTests(TestCase):
    """Verify transition policy, audit output, and idempotency boundaries."""

    def setUp(self):
        """Create the smallest shared domain graph required by reservations."""

        self.at = timezone.now().replace(microsecond=0)
        self.user = User.objects.create_user(
            username="lifecycle-customer",
            email="lifecycle@example.com",
            password="Str0ngPass!23",
            role=Roles.STUDENT,
        )
        self.floor = Floor.objects.create(name="Lifecycle", code="LC", sort_order=99)
        self.slot = Slot.objects.create(
            floor=self.floor,
            code="LC-01",
            slot_type=VehicleType.CAR,
        )

    def make_reservation(self, *, status, start_at=None, end_at=None):
        """Build a reservation around the deterministic service timestamp."""

        return Reservation.objects.create(
            customer=self.user,
            slot=self.slot,
            status=status,
            start_at=start_at or self.at - timedelta(hours=2),
            end_at=end_at or self.at - timedelta(hours=1),
        )

    def age_reservation(self, reservation, *, created_at):
        """Set auto-managed creation time directly to model an old payment hold."""

        Reservation.objects.filter(pk=reservation.pk).update(created_at=created_at)
        reservation.refresh_from_db()

    def test_ended_occupied_reservation_completes_with_activity(self):
        """An occupied session ending exactly at the cutoff is completed."""

        reservation = self.make_reservation(
            status=ReservationStatus.OCCUPIED,
            end_at=self.at,
        )

        summary = process_reservation_lifecycle(at=self.at, payment_grace=None)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.COMPLETED)
        self.assertEqual(summary.completed, 1)
        self.assertTrue(
            ActivityLog.objects.filter(action="reservation.auto_completed").exists()
        )

    def test_ended_reserved_reservation_cancels_with_distinct_activity(self):
        """An unoccupied reservation past its end releases the slot as cancelled."""

        reservation = self.make_reservation(status=ReservationStatus.RESERVED)

        summary = process_reservation_lifecycle(at=self.at, payment_grace=None)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.CANCELLED)
        self.assertEqual(summary.ended_cancelled, 1)
        self.assertTrue(
            ActivityLog.objects.filter(action="reservation.ended_unoccupied").exists()
        )

    def test_future_and_terminal_reservations_remain_unchanged(self):
        """No lifecycle rule should rewrite future, cancelled, or completed rows."""

        future = self.make_reservation(
            status=ReservationStatus.RESERVED,
            start_at=self.at + timedelta(hours=1),
            end_at=self.at + timedelta(hours=2),
        )
        cancelled = self.make_reservation(status=ReservationStatus.CANCELLED)
        completed = self.make_reservation(status=ReservationStatus.COMPLETED)

        summary = process_reservation_lifecycle(at=self.at, payment_grace=None)

        self.assertEqual(summary.total, 0)
        for reservation in (future, cancelled, completed):
            reservation.refresh_from_db()
        self.assertEqual(future.status, ReservationStatus.RESERVED)
        self.assertEqual(cancelled.status, ReservationStatus.CANCELLED)
        self.assertEqual(completed.status, ReservationStatus.COMPLETED)

    def test_repeated_processing_is_idempotent(self):
        """A second scheduler pass writes neither a transition nor another log."""

        reservation = self.make_reservation(status=ReservationStatus.OCCUPIED)

        first = process_reservation_lifecycle(at=self.at, payment_grace=None)
        second = process_reservation_lifecycle(at=self.at, payment_grace=None)

        self.assertEqual(first.completed, 1)
        self.assertEqual(second.total, 0)
        self.assertEqual(
            ActivityLog.objects.filter(
                action="reservation.auto_completed",
                description__contains=reservation.code,
            ).count(),
            1,
        )

    def test_old_future_hold_with_non_paid_payment_expires(self):
        """Configured grace expiry cancels only an old future hold with payment."""

        reservation = self.make_reservation(
            status=ReservationStatus.RESERVED,
            start_at=self.at + timedelta(hours=2),
            end_at=self.at + timedelta(hours=3),
        )
        self.age_reservation(
            reservation,
            created_at=self.at - timedelta(minutes=31),
        )
        Payment.objects.create(
            reservation=reservation,
            amount_cents=reservation.fee_cents,
            status=PaymentStatus.PENDING,
        )

        summary = process_reservation_lifecycle(
            at=self.at,
            payment_grace=timedelta(minutes=30),
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.CANCELLED)
        self.assertEqual(summary.unpaid_cancelled, 1)
        self.assertTrue(
            ActivityLog.objects.filter(
                action="reservation.unpaid_hold_expired",
                description__contains=reservation.code,
            ).exists()
        )

    def test_unpaid_expiry_requires_payment_and_preserves_paid_booking(self):
        """No-payment and paid reservations are conservative exclusions."""

        without_payment = self.make_reservation(
            status=ReservationStatus.RESERVED,
            start_at=self.at + timedelta(hours=2),
            end_at=self.at + timedelta(hours=3),
        )
        paid = self.make_reservation(
            status=ReservationStatus.RESERVED,
            start_at=self.at + timedelta(hours=4),
            end_at=self.at + timedelta(hours=5),
        )
        for reservation in (without_payment, paid):
            self.age_reservation(
                reservation,
                created_at=self.at - timedelta(hours=1),
            )
        Payment.objects.create(
            reservation=paid,
            amount_cents=paid.fee_cents,
            status=PaymentStatus.PAID,
            paid_at=self.at - timedelta(minutes=10),
        )

        summary = process_reservation_lifecycle(
            at=self.at,
            payment_grace=timedelta(minutes=30),
        )

        self.assertEqual(summary.unpaid_cancelled, 0)
        without_payment.refresh_from_db()
        paid.refresh_from_db()
        self.assertEqual(without_payment.status, ReservationStatus.RESERVED)
        self.assertEqual(paid.status, ReservationStatus.RESERVED)

    @override_settings(RESERVATION_PAYMENT_GRACE_MINUTES=0)
    def test_unpaid_expiry_is_disabled_by_conservative_zero_setting(self):
        """A disabled deployment setting cannot unexpectedly cancel old holds."""

        reservation = self.make_reservation(
            status=ReservationStatus.RESERVED,
            start_at=self.at + timedelta(hours=2),
            end_at=self.at + timedelta(hours=3),
        )
        self.age_reservation(reservation, created_at=self.at - timedelta(days=1))
        Payment.objects.create(
            reservation=reservation,
            amount_cents=reservation.fee_cents,
            status=PaymentStatus.FAILED,
        )

        summary = process_reservation_lifecycle(at=self.at)

        reservation.refresh_from_db()
        self.assertEqual(summary.unpaid_cancelled, 0)
        self.assertEqual(reservation.status, ReservationStatus.RESERVED)

    def test_dry_run_counts_without_writes_or_activity(self):
        """Preview mode reports work while leaving both state and audit untouched."""

        reservation = self.make_reservation(status=ReservationStatus.OCCUPIED)

        summary = process_reservation_lifecycle(
            at=self.at,
            dry_run=True,
            payment_grace=None,
        )

        reservation.refresh_from_db()
        self.assertEqual(summary.completed, 1)
        self.assertEqual(reservation.status, ReservationStatus.OCCUPIED)
        self.assertFalse(ActivityLog.objects.exists())

    @override_settings(RESERVATION_PAYMENT_GRACE_MINUTES=0)
    def test_management_command_supports_dry_run_and_iso_at(self):
        """The scheduler-facing command accepts deterministic ISO timestamps."""

        reservation = self.make_reservation(status=ReservationStatus.OCCUPIED)
        output = StringIO()

        call_command(
            "process_reservations",
            dry_run=True,
            at=self.at.isoformat(),
            stdout=output,
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.OCCUPIED)
        self.assertIn("DRY RUN completed=1", output.getvalue())
