from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse


def home(request):
    """Public landing page.

    Signed-in users are routed to the workspace for their effective role. The
    fallback keeps the landing page usable if an optional URL namespace is
    temporarily unavailable during maintenance or partial deployments.
    """
    if request.user.is_authenticated:
        if request.user.is_staff or getattr(request.user, "is_admin_role", False):
            target = "dashboard:home"
        else:
            target = "parking:slots"
        try:
            return redirect(reverse(target))
        except NoReverseMatch:
            return render(request, "core/home.html")
    return render(request, "core/home.html")
