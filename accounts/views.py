from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import ActivityLog, log_activity

from .decorators import customer_required
from .forms import (
    AdminRegistrationForm,
    CustomerRegistrationForm,
    ProfileForm,
    VehicleForm,
)
from .models import Vehicle


def register_customer(request):
    """Self-registration for students, employees, and visitors."""
    if request.user.is_authenticated:
        return redirect("core:home")
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity(
                "user.registered",
                f"{user.get_role_display()} account created",
                actor=user,
                request=request,
            )
            login(request, user)
            messages.success(request, "Welcome! Your account is ready.")
            return redirect("core:home")
    else:
        form = CustomerRegistrationForm()
    return render(
        request,
        "accounts/register.html",
        {"form": form, "heading": "Create your account", "is_admin": False},
    )


def register_admin(request):
    """Separate administrator registration (access-code gated)."""
    # Conceal and disable this privileged endpoint unless an operator has
    # deliberately enabled the temporary self-registration workflow.
    if not settings.ADMIN_SIGNUP_ENABLED:
        raise Http404("Administrator self-registration is disabled.")
    if request.user.is_authenticated:
        return redirect("core:home")
    if request.method == "POST":
        form = AdminRegistrationForm(request.POST)

        # Count only access-code failures and use the persisted audit table so
        # throttling cannot be reset by switching application workers.
        client_ip = getattr(request, "client_ip", None)
        window_start = timezone.now() - timedelta(
            minutes=settings.ADMIN_SIGNUP_WINDOW_MINUTES
        )
        recent_failures = ActivityLog.objects.filter(
            action="admin.signup_failed",
            ip_address=client_ip,
            created_at__gte=window_start,
        ).count()
        if recent_failures >= settings.ADMIN_SIGNUP_MAX_ATTEMPTS:
            form.add_error(
                None,
                "Too many administrator enrollment attempts. Try again later.",
            )
            log_activity(
                "admin.signup_throttled",
                "Administrator enrollment rate limit reached",
                request=request,
            )
            return render(
                request,
                "accounts/register.html",
                {"form": form, "heading": "Administrator registration", "is_admin": True},
                status=429,
            )

        if form.is_valid():
            user = form.save()
            log_activity(
                "admin.registered",
                "Administrator account created",
                actor=user,
                request=request,
            )
            login(request, user)
            messages.success(request, "Administrator account created.")
            return redirect("core:home")
        if "access_code" in form.errors:
            # Never record the supplied code or other credentials.
            log_activity(
                "admin.signup_failed",
                "Incorrect administrator enrollment code",
                request=request,
            )
    else:
        form = AdminRegistrationForm()
    return render(
        request,
        "accounts/register.html",
        {"form": form, "heading": "Administrator registration", "is_admin": True},
    )


@login_required
def profile(request):
    """View and edit the signed-in user's profile."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            log_activity("profile.updated", actor=request.user, request=request)
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})


@customer_required
def vehicle_list(request):
    vehicles = request.user.vehicles.all()
    return render(request, "accounts/vehicle_list.html", {"vehicles": vehicles})


@customer_required
def vehicle_add(request):
    if request.method == "POST":
        form = VehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.owner = request.user
            vehicle.save()
            log_activity(
                "vehicle.added",
                vehicle.plate_number,
                actor=request.user,
                request=request,
            )
            messages.success(request, "Vehicle added.")
            return redirect("accounts:vehicles")
    else:
        form = VehicleForm()
    return render(
        request,
        "accounts/vehicle_form.html",
        {"form": form, "heading": "Add vehicle"},
    )


@customer_required
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk, owner=request.user)
    if request.method == "POST":
        form = VehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehicle updated.")
            return redirect("accounts:vehicles")
    else:
        form = VehicleForm(instance=vehicle)
    return render(
        request,
        "accounts/vehicle_form.html",
        {"form": form, "heading": "Edit vehicle"},
    )


@customer_required
def vehicle_delete(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk, owner=request.user)
    if request.method == "POST":
        plate = vehicle.plate_number
        vehicle.delete()
        log_activity("vehicle.removed", plate, actor=request.user, request=request)
        messages.success(request, "Vehicle removed.")
        return redirect("accounts:vehicles")
    return render(
        request, "accounts/vehicle_confirm_delete.html", {"vehicle": vehicle}
    )
