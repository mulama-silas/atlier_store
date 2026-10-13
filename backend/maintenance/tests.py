"""Tests for the gated demo-data reset.

The properties that matter: the feature is unreachable when disabled, a
non-superuser cannot reach it even when enabled, GET never deletes, and admin
accounts always survive.
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from admin_ui.models import AdminNotification
from audit.models import AuditLog
from catalog.models import Category, Product, ProductVariant
from maintenance.management.commands.reset_demo_data import (
    DELETION_ORDER,
    PRESERVED,
    build_plan,
    reset_demo_data,
)
from orders.models import Order


def _superuser():
    return get_user_model().objects.create_superuser(
        username=f'reset-admin-{uuid.uuid4().hex[:8]}',
        password='pw', email='admin@example.com')


def _catalogue():
    category = Category.objects.create(name='Dresses', slug=f'd{uuid.uuid4().hex[:6]}')
    product = Product.objects.create(
        name='Luna', category=category, price_minor=1000)
    ProductVariant.objects.create(product=product, sku=f'SKU{uuid.uuid4().hex[:8]}')
    return category, product


class ResetDisabledTests(TestCase):
    """ENABLE_DATA_RESET off must make the whole feature not exist."""

    def setUp(self):
        self.admin = _superuser()
        self.client.force_login(self.admin)

    def test_page_is_404_when_disabled(self):
        response = self.client.get(reverse('admin-reset-data'))
        self.assertEqual(response.status_code, 404)

    def test_confirm_endpoint_is_404_when_disabled(self):
        response = self.client.post(
            reverse('admin-reset-data-confirm'), {'confirm': 'WIPE'})
        self.assertEqual(response.status_code, 404)

    def test_nothing_is_deleted_when_disabled(self):
        _catalogue()
        self.client.post(
            reverse('admin-reset-data-confirm'), {'confirm': 'WIPE'})
        self.assertTrue(Product.objects.exists())


class ResetCommandGateTests(TestCase):
    def test_command_refuses_when_disabled(self):
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(ENABLE_DATA_RESET=False):
            with self.assertRaises(CommandError) as ctx:
                call_command('reset_demo_data', stdout=StringIO())

        self.assertIn('ENABLE_DATA_RESET', str(ctx.exception))


class ResetAuthorizationTests(TestCase):
    @override_settings(ENABLE_DATA_RESET=True)
    def test_staff_without_superuser_is_denied(self):
        """A permission code could be granted to other roles; is_superuser
        cannot."""
        staff = get_user_model().objects.create_user(
            username=f'staff-{uuid.uuid4().hex[:8]}', password='pw',
            is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse('admin-reset-data'))

        self.assertEqual(response.status_code, 403)

    @override_settings(ENABLE_DATA_RESET=True)
    def test_superuser_can_view_preview(self):
        self.client.force_login(_superuser())

        response = self.client.get(reverse('admin-reset-data'))

        self.assertEqual(response.status_code, 200)


class ResetSafetyTests(TestCase):
    def setUp(self):
        self.admin = _superuser()
        self.client.force_login(self.admin)

    @override_settings(ENABLE_DATA_RESET=True)
    def test_get_never_deletes(self):
        """A crawler or prefetch must not be able to wipe the store."""
        _catalogue()

        response = self.client.get(reverse('admin-reset-data-confirm'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.exists())

    @override_settings(ENABLE_DATA_RESET=True)
    def test_wrong_confirmation_deletes_nothing(self):
        _catalogue()

        self.client.post(
            reverse('admin-reset-data-confirm'), {'confirm': 'yes'})

        self.assertTrue(Product.objects.exists())

    @override_settings(ENABLE_DATA_RESET=True)
    def test_blank_confirmation_deletes_nothing(self):
        _catalogue()

        self.client.post(reverse('admin-reset-data-confirm'), {})

        self.assertTrue(Product.objects.exists())

    @override_settings(ENABLE_DATA_RESET=True)
    def test_confirmation_is_case_insensitive_but_exact_word_required(self):
        _catalogue()

        self.client.post(
            reverse('admin-reset-data-confirm'), {'confirm': 'please wipe'})
        self.assertTrue(Product.objects.exists(), 'a phrase must not count')

        self.client.post(
            reverse('admin-reset-data-confirm'), {'confirm': 'wipe'})
        self.assertFalse(Product.objects.exists())


class ResetExecutionTests(TestCase):
    """These use reset_demo_data() directly -- the page layer is covered above."""

    def setUp(self):
        self.admin = _superuser()
        self.staff = get_user_model().objects.create_user(
            username=f'staff-{uuid.uuid4().hex[:8]}', password='pw',
            is_staff=True)

    def test_removes_catalogue_and_orders(self):
        _catalogue()
        Order.objects.create(
            order_number=f'MZ-{uuid.uuid4().hex[:10].upper()}',
            customer={'name': 'X'}, subtotal_minor=100, total_minor=100)
        AdminNotification.objects.create(
            recipient=self.admin, category='order', title='t', message='m')
        AuditLog.objects.create(action='test', object_type='order', object_id='1')

        summary = reset_demo_data()

        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(AdminNotification.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertTrue(summary['deleted'])

    def test_preserves_admin_and_staff_accounts(self):
        """The entire point: staff keep their login."""
        _catalogue()

        reset_demo_data()

        self.assertTrue(
            get_user_model().objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(
            get_user_model().objects.filter(pk=self.staff.pk).exists())
        self.assertTrue(get_user_model().objects.filter(
            pk=self.admin.pk).first().is_superuser)

    def test_preserves_permission_and_role_tables(self):
        from access_control.models import Permission, Role

        roles_before = Role.objects.count()
        perms_before = Permission.objects.count()

        reset_demo_data()

        self.assertEqual(Role.objects.count(), roles_before)
        self.assertEqual(Permission.objects.count(), perms_before)

    def test_plan_lists_only_deletable_models(self):
        plan = build_plan()
        labels = [label for label, _ in plan]

        for preserved in ('auth.user', 'auth.permission', 'auth.group',
                          'access_control.role', 'django.migrations'):
            self.assertNotIn(preserved, labels)

    def test_every_declared_model_resolves(self):
        """A typo in DELETION_ORDER silently skips that table -- catch it."""
        from django.apps import apps

        unresolved = []
        for label in DELETION_ORDER:
            try:
                apps.get_model(label)
            except LookupError:
                unresolved.append(label)

        self.assertEqual(unresolved, [], f'Unresolvable model labels: {unresolved}')

    def test_preserved_list_documents_the_keep_set(self):
        joined = ' '.join(PRESERVED)
        self.assertIn('auth.user', joined)
        self.assertIn('auth.permission', joined)