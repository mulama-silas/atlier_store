from django.conf import settings


def maintenance_flags(request):
    """Expose opt-in destructive features to the admin templates.

    The demo-data reset page only appears in navigation while
    ``ENABLE_DATA_RESET`` is set. Hiding the link is a convenience, not the
    control: the view itself answers 404 without the flag, so forgetting to
    remove the variable later cannot leave a live delete button behind.
    """
    return {
        'reset_enabled': bool(getattr(settings, 'ENABLE_DATA_RESET', False)),
    }