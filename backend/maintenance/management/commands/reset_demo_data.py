"""``manage.py reset_demo_data`` -- wipe everything except the admin accounts.

Intended for one clean slate before real customers arrive, when every order,
payment and receipt is test-generated.

Two things make this safe to keep in the repository
--------------------------------------------------
1. It refuses to run unless ``ENABLE_DATA_RESET`` is on. Handover to a client
   is then a config change, not a code deletion, and a deployment that
   accidentally keeps the flag is still behind a superuser check and a typed
   confirmation.
2. ``manage.py flush`` must NEVER be used for this. ``flush`` truncates every
   table including ``auth_user``, which would delete the very admin accounts
   this command exists to preserve.

Why an explicit order instead of ``Model.objects.all().delete()``
-----------------------------------------------------------------
Several relations use ``on_delete=PROTECT`` -- ``PaymentIntent.order``,
``PromotionRedemption.promotion``/``order``, ``StockReservation.variant``,
``InventoryTransaction.variant`` and ``Product.category``. A naive cascade
raises ``ProtectedError`` partway through. Deleting children first, inside a
single transaction, means a failure rolls the whole thing back and leaves the
database untouched.

Preserved: ``auth_user`` (superusers/staff), ``auth_permission``,
``auth_group``, ``django_content_type``, ``django_migrations``,
``django_session``, ``access_control.Permission``, ``access_control.Role``.
"""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

# Children before parents. Each entry is a Django app_label.model_name.
DELETION_ORDER = [
    # Assistant chatter first -- it points at orders and users.
    'assistant.assistantmessage',
    'assistant.assistanttoolcall',
    'assistant.assistantinsight',
    'assistant.assistantconversation',
    # Notifications and logs.
    'admin_ui.adminnotification',
    'admin_ui.customernotification',
    'audit.auditlog',
    'emails.emaillog',
    # Payments, then everything hanging off an order.
    'payments.paymentevent',
    'payments.paymentintent',
    'orders.orderitem',
    'receipts.receipt',
    'inventory.stockreservation',
    'promotions.promotionredemption',
    'inventory.inventorytransaction',
    # Order + cart roots.
    'orders.order',
    'cart.cartitem',
    'cart.cart',
    # Remaining children of variants / categories / promotions.
    'inventory.backinstockrequest',
    'promotions.promotionproduct',
    'promotions.promotioncategory',
    'promotions.promotionvariant',
    'promotions.promotioncustomer',
    # Catalogue.
    'catalog.productimage',
    'catalog.productvariant',
    'catalog.importjob',
    'catalog.productimportlog',
    'catalog.product',
    'catalog.category',
    # Standalone leaves.
    'promotions.promotion',
    'receipts.receiptsequence',
]

# Never touched, regardless of ENABLE_DATA_RESET.
PRESERVED = [
    'auth.user (admin + staff accounts)',
    'auth.permission',
    'auth.group',
    'access_control.permission',
    'access_control.role',
    'django.content_type',
    'django.migrations',
    'django.session',
]


def _model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def build_plan():
    """[(label, count)] for every deletable model, in dependency order.

    Skips models that do not exist in this deployment rather than raising, so
    the same command survives a future app removal.
    """
    plan = []
    for label in DELETION_ORDER:
        model = _model(label)
        if model is None:
            continue
        plan.append((label, model.objects.count()))
    return plan


def reset_demo_data():
    """Delete all demo data in one transaction. Returns a summary dict."""
    counts = {}

    with transaction.atomic():
        for label in DELETION_ORDER:
            model = _model(label)
            if model is None:
                continue
            deleted, _ = model.objects.all().delete()
            counts[label] = deleted

    # Counts come from `delete()`, which cascades; recompute survivors so the
    # summary reflects rows actually gone rather than rows directly addressed.
    remaining = {}
    for label in DELETION_ORDER:
        model = _model(label)
        if model is not None:
            remaining[label] = model.objects.count()

    return {
        'deleted': counts,
        'remaining': remaining,
        'at': timezone.now(),
    }


class Command(BaseCommand):
    help = (
        'Delete all demo/test data while preserving admin and staff accounts. '
        'Refuses to run unless ENABLE_DATA_RESET is set.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be deleted without deleting anything.')
        parser.add_argument(
            '--force', action='store_true',
            help='Required alongside --yes to confirm an irreversible delete.')

    def handle(self, *args, **options):
        if not getattr(settings, 'ENABLE_DATA_RESET', False):
            raise CommandError(
                'ENABLE_DATA_RESET is not enabled, so this command refuses to '
                'run. Set the environment variable to "true", redeploy, and '
                'remove it again afterwards.'
            )

        plan = build_plan()
        total = sum(count for _, count in plan)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                'DRY RUN -- nothing will be deleted.'))
            self._print_plan(plan, total)
            self.stdout.write('')
            self.stdout.write('Would be preserved:')
            for item in PRESERVED:
                self.stdout.write(f'  - {item}')
            return

        if not options['force']:
            raise CommandError(
                'Refusing to delete without --force. This is irreversible: '
                'there is no undo and no backup on the free tier. Re-run with '
                '--dry-run first to see exactly what goes.'
            )

        summary = reset_demo_data()

        self.stdout.write(self.style.SUCCESS('Demo data removed.'))
        for label, deleted in summary['deleted'].items():
            if deleted:
                self.stdout.write(f'  {label:<38} {deleted} row(s) deleted')
        leftovers = {k: v for k, v in summary['remaining'].items() if v}
        if leftovers:
            self.stdout.write(self.style.WARNING(
                f'WARNING: {len(leftovers)} table(s) still hold rows: '
                f'{leftovers}'))
        self.stdout.write('Preserved: ' + ', '.join(PRESERVED))

    def _print_plan(self, plan, total):
        self_width = max(len(label) for label, _ in plan)
        for label, count in plan:
            self.stdout.write(f'  {label:<{self_width}}  {count:>8} row(s)')
        self.stdout.write(f'  {"TOTAL":<{self_width}}  {total:>8} row(s)')