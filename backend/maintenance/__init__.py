"""One-shot maintenance operations (demo-data reset).

Deliberately separate from the business apps: nothing here runs on a request
path except the gated admin page in ``admin_ui``. The destructive command is
refused unless ``ENABLE_DATA_RESET`` is on, so forgetting to remove the env var
is not catastrophic and leaving it on is not accidental.
"""

default_app_config = 'maintenance.apps.MaintenanceConfig'