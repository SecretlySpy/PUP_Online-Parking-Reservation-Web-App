from django.conf import settings


def site(request):
    """Expose branding constants to every template."""
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_SHORT_NAME": settings.SITE_SHORT_NAME,
    }
