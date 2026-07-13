from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def _require(test, request, view, args, kwargs):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not test(request.user):
        raise PermissionDenied
    return view(request, *args, **kwargs)


def admin_required(view):
    """Allow only administrators (ADMIN role or staff)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        return _require(lambda u: u.is_admin_role, request, view, args, kwargs)

    return wrapper


def customer_required(view):
    """Allow only parking customers (student/employee/visitor)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        def test(user):
            if user.is_customer_role:
                return True
            # Admins have their own workspace — nudge them there.
            messages.info(request, "Switch to a customer account to book slots.")
            return False

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.is_admin_role:
            # Route admins through the central dispatcher so role navigation
            # remains defined in one place instead of duplicating dashboard URLs.
            return redirect("core:home")
        if not test(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
