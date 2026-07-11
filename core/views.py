from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse


def home(request):
    """Public landing page.

    Signed-in users are routed to their workspace. The target views are built
    in later phases; until they exist we fall back to an authenticated welcome
    page so every phase stays independently runnable.
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
