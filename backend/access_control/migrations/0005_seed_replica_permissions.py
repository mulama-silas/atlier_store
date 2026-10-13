from django.db import migrations


def forward(apps, schema_editor):
    """Seed the Supabase replica permission group.

    Permissions must arrive as a data migration, not via `manage.py
    seed_roles`: the free Render plan has no shell, so only `migrate` is
    guaranteed to run (the Dockerfile chains it before gunicorn). Without this,
    the replica nav link stays hidden and /admin/dashboard/replica/ 403s for
    everyone, because no Permission row for the two new codes exists.

    seed_system_permissions_and_roles is idempotent, and it re-syncs every
    default role's permission set, so super_admin picks the codes up too.
    """
    from access_control.seed import seed_system_permissions_and_roles

    Permission = apps.get_model("access_control", "Permission")
    Role = apps.get_model("access_control", "Role")

    seed_system_permissions_and_roles(Permission, Role)


def backward(apps, schema_editor):
    """Re-sync from the catalogue. The two codes are removed only if they are
    no longer declared in permissions_catalog.PERMISSIONS."""
    from access_control.seed import seed_system_permissions_and_roles

    Permission = apps.get_model("access_control", "Permission")
    Role = apps.get_model("access_control", "Role")

    seed_system_permissions_and_roles(Permission, Role)


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0004_seed_promotion_permissions"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]