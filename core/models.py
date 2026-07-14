import logging

from django.conf import settings
from django.db import models
from django.db.models import Q


logger = logging.getLogger(__name__)


class ActivityLog(models.Model):
    """Audit trail of meaningful system events, surfaced in admin reports.

    Records are written via :func:`log_activity` at domain moments (a user
    registers, a reservation is booked, a payment is paid, a slot is set to
    maintenance, ...). ``actor`` is kept nullable so the log survives user
    deletion; ``actor_label`` preserves a readable name in that case.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    actor_label = models.CharField(max_length=150, blank=True)
    # The customer the event concerns (may differ from actor when an admin or
    # the automated scheduler acts). Powers the customer-facing activity feed.
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_activities",
    )
    action = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "activity log entry"
        verbose_name_plural = "activity log"

    def __str__(self):
        who = self.actor_label or "system"
        return f"{who}: {self.action}"


def log_activity(action, description="", actor=None, request=None, target_user=None):
    """Create an :class:`ActivityLog` entry. Never raises to the caller.

    Safe to call before migrations exist (e.g. during early bootstrap) — any
    database error is swallowed so logging can never break the request flow.

    ``target_user`` names the customer an event concerns (for the activity
    feed); it defaults to ``actor`` when omitted so self-service actions are
    attributed to the customer automatically.
    """
    if actor is None and request is not None:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            actor = user
    if target_user is None:
        target_user = actor
    ip = getattr(request, "client_ip", None) if request is not None else None
    try:
        return ActivityLog.objects.create(
            actor=actor if (actor and getattr(actor, "pk", None)) else None,
            actor_label=(str(actor) if actor else "system")[:150],
            target_user=target_user if (target_user and getattr(target_user, "pk", None)) else None,
            action=action[:64],
            description=description[:255],
            ip_address=ip,
        )
    except Exception:
        # Audit logging remains non-fatal, but operators still need the original
        # exception to diagnose a missing migration or database outage.
        logger.exception("Unable to persist activity log action=%s", action)
        return None


def customer_activity(user):
    """Return the activity feed for one customer, newest first.

    Includes events the customer performed (``actor``) and events performed on
    their behalf by an admin or the scheduler (``target_user``).
    """
    return (
        ActivityLog.objects.filter(Q(actor=user) | Q(target_user=user))
        .select_related("actor")
        .order_by("-created_at")
    )
