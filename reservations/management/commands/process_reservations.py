"""Process due reservation lifecycle transitions from a scheduler."""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from reservations.lifecycle import process_reservation_lifecycle


class Command(BaseCommand):
    """Expose lifecycle processing as an idempotent operations command."""

    help = "Complete or cancel due reservations and expire configured unpaid holds."

    def add_arguments(self, parser):
        """Register safe preview and deterministic timestamp options."""

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report due transitions without changing reservations or activity logs.",
        )
        parser.add_argument(
            "--at",
            metavar="ISO_DATETIME",
            help=(
                "Process as of an ISO-8601 datetime. Naive values use Django's "
                "configured time zone."
            ),
        )

    def handle(self, *args, **options):
        """Parse the effective time, run the service, and print parseable counts."""

        at = self._parse_at(options.get("at"))
        dry_run = options["dry_run"]
        try:
            summary = process_reservation_lifecycle(at=at, dry_run=dry_run)
        except ValueError as exc:
            # Configuration errors should fail the scheduled job visibly rather
            # than silently skipping lifecycle work with an unsafe assumption.
            raise CommandError(str(exc)) from exc

        mode = "DRY RUN" if dry_run else "APPLIED"
        self.stdout.write(
            f"{mode} completed={summary.completed} "
            f"ended_cancelled={summary.ended_cancelled} "
            f"unpaid_cancelled={summary.unpaid_cancelled} total={summary.total}"
        )

    @staticmethod
    def _parse_at(raw_value):
        """Parse ``--at`` and make naive input explicit in the project timezone."""

        if not raw_value:
            return timezone.now()

        parsed = parse_datetime(raw_value)
        if parsed is None:
            raise CommandError(
                "--at must be a valid ISO-8601 datetime, for example "
                "2026-07-12T18:00:00+08:00."
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
