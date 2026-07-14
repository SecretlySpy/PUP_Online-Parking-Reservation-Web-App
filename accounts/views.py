from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import ActivityLog, customer_activity, log_activity

from .decorators import customer_required
from .forms import (
    AdminRegistrationForm,
    CustomerRegistrationForm,
    LoginForm,
    ProfileForm,
    VehicleForm,
)
from .models import Vehicle
from .verification import (
    make_email_token,
    read_email_token,
    send_verification_email,
)

User = get_user_model()


def register_customer(request):
    """Self-registration for students, employees, and visitors."""
    if request.user.is_authenticated:
        return redirect("core:home")
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # New self-registrations must confirm their email before booking.
            user.email_verified = False
            user.save()
            log_activity(
                "user.registered",
                f"{user.get_role_display()} account created",
                actor=user,
                request=request,
            )
            send_verification_email(user)
            login(request, user)
            messages.success(
                request,
                "Welcome! We've emailed you a link to verify your address — "
                "verify it to start booking.",
            )
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
def activity(request):
    """A customer-facing feed of their own booking/payment events."""
    entries = customer_activity(request.user)
    page = Paginator(entries, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/activity.html",
        {"entries": page.object_list, "page_obj": page},
    )


# --- Email verification -----------------------------------------------------

def verify_email(request, token):
    """Confirm an email address from the signed link and unlock booking."""
    payload = read_email_token(token, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
    if payload:
        user = User.objects.filter(
            pk=payload.get("uid"), email=payload.get("email")
        ).first()
        if user:
            if not user.email_verified:
                user.email_verified = True
                user.save(update_fields=["email_verified"])
                log_activity(
                    "user.email_verified", "Email address verified",
                    actor=user, request=request, target_user=user,
                )
            messages.success(request, "Your email is verified — you can now book slots.")
            return redirect("core:home")
    messages.error(request, "That verification link is invalid or has expired.")
    return redirect("accounts:verify_notice")


@login_required
def verify_notice(request):
    """Explain that verification is required and offer to resend the link."""
    if getattr(request.user, "email_verified", True):
        return redirect("core:home")
    return render(request, "accounts/verify_notice.html")


@login_required
@require_POST
def resend_verification(request):
    """Re-send the verification email to the signed-in, unverified user."""
    if not request.user.email_verified:
        send_verification_email(request.user)
        messages.success(request, "Verification email sent. Please check your inbox.")
    return redirect("accounts:verify_notice")


class ThrottledLoginView(auth_views.LoginView):
    """Login that rate-limits repeated failures by client IP (audit-backed)."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _recent_failures(self):
        window_start = timezone.now() - timedelta(
            minutes=settings.LOGIN_ATTEMPT_WINDOW_MINUTES
        )
        return ActivityLog.objects.filter(
            action="auth.login_failed",
            ip_address=getattr(self.request, "client_ip", None),
            created_at__gte=window_start,
        ).count()

    def post(self, request, *args, **kwargs):
        if self._recent_failures() >= settings.LOGIN_MAX_ATTEMPTS:
            form = self.get_form()
            form.add_error(
                None,
                "Too many failed sign-in attempts. Please wait a few minutes and try again.",
            )
            log_activity("auth.login_throttled", "Login rate limit reached", request=request)
            return self.render_to_response(
                self.get_context_data(form=form), status=429
            )
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # Record the failed attempt (never the credentials) for throttling.
        log_activity("auth.login_failed", "Failed sign-in attempt", request=self.request)
        return super().form_invalid(form)


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
