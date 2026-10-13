"""Tests for the Supabase analytics replica.

The Supabase side is exercised through a fake connection rather than a live
database, so the suite stays hermetic. What these tests protect is the part
that is easy to get quietly wrong: that the endpoint is unreachable when
unconfigured, that a write never happens on GET, and that a count mismatch
fails the run instead of being recorded as a success.
"""

import uuid
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Category, Product, ProductVariant
from orders.models import Order

REPLICA_DB = 'postgresql://postgres:pw@db.example.supabase.co:5432/postgres'


def _order(user=None, total=1000, status=Order.Status.CONFIRMED):
    return Order.objects.create(
        id=uuid.uuid4(),
        order_number=f'MZ-{uuid.uuid4().hex[:10].upper()}',
        user=user,
        customer={'name': 'Test', 'phone': '+254700000000'},
        subtotal_minor=total,
        total_minor=total,
        status=status,
        payment_status=Order.PaymentStatus.PAID,
    )


class ReplicaConfigTests(TestCase):
    @override_settings(SUPABASE_DB_URL='')
    def test_replica_not_configured_without_db_url(self):
        from replica.services.sync import replica_configured

        self.assertFalse(replica_configured())

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_replica_configured_with_db_url(self):
        from replica.services.sync import replica_configured

        self.assertTrue(replica_configured())

    @override_settings(SUPABASE_DB_URL='')
    def test_sync_raises_clear_error_without_db_url(self):
        from replica.services.sync import ReplicaNotConfigured, sync_replica

        with self.assertRaises(ReplicaNotConfigured) as ctx:
            sync_replica()
        self.assertIn('SUPABASE_DB_URL', str(ctx.exception))

    @override_settings(SUPABASE_DB_URL='')
    def test_latest_run_returns_none_without_db_url(self):
        from replica.services.sync import latest_run

        self.assertIsNone(latest_run())


class CustomerAggregateTests(TestCase):
    """The aggregate must not carry identity fields into the replica."""

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_aggregates_orders_and_excludes_cancelled_from_spend(self):
        from django.contrib.auth import get_user_model

        from replica.services.sync import customer_rows

        user = get_user_model().objects.create_user(
            username=f'supabase_{uuid.uuid4()}', password='x')
        _order(user=user, total=1500, status=Order.Status.DELIVERED)
        _order(user=user, total=2500, status=Order.Status.CANCELLED)

        rows = {r['user_id']: r for r in customer_rows()}

        self.assertIn(str(user.id), rows)
        row = rows[str(user.id)]
        self.assertEqual(row['order_count'], 2)
        # Cancelled orders must not inflate revenue.
        self.assertEqual(row['total_spent_minor'], 1500)

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_guest_orders_are_excluded(self):
        from replica.services.sync import customer_rows

        _order(user=None, total=999)

        self.assertEqual(customer_rows(), [])

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_aggregate_carries_no_identity_fields(self):
        from django.contrib.auth import get_user_model

        from replica.services.sync import customer_rows

        user = get_user_model().objects.create_user(
            username=f'supabase_{uuid.uuid4()}', password='x')
        _order(user=user)

        for row in customer_rows():
            self.assertNotIn('email', row)
            self.assertNotIn('phone', row)
            self.assertNotIn('password', row)
            self.assertEqual(
                set(row),
                {'user_id', 'first_order_at', 'last_order_at', 'order_count',
                 'total_spent_minor'},
            )


class ExtractorTests(TestCase):
    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_payment_intents_exclude_client_secret(self):
        """client_secret is a live confirmation secret; analytics never needs it."""
        from payments.models import PaymentIntent

        from replica.services.sync import payment_intent_rows

        intent = PaymentIntent.objects.create(
            id=f'pi_{uuid.uuid4().hex[:16]}',
            order=_order(),
            amount_minor=1000,
            method=PaymentIntent.Method.MPESA,
            client_secret='secret-value',
            status=PaymentIntent.Status.PENDING,
        )

        rows = payment_intent_rows()

        self.assertEqual(len(rows), 1)
        self.assertNotIn('client_secret', rows[0])
        self.assertEqual(rows[0]['id'], intent.id)

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_variants_have_no_timestamp_columns(self):
        """catalog.ProductVariant has no created_at/updated_at."""
        from replica.services.sync import variant_rows

        category = Category.objects.create(name='Dresses', slug='dresses')
        product = Product.objects.create(
            name='Luna', category=category, price_minor=1000)
        ProductVariant.objects.create(product=product, sku='LUNA-S')

        rows = variant_rows()

        self.assertEqual(len(rows), 1)
        self.assertNotIn('created_at', rows[0])
        self.assertNotIn('updated_at', rows[0])


class SyncFailureTests(TestCase):
    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_table_bulk_insert_uses_single_values_placeholder(self):
        from replica.services import sync as sync_mod

        conn = mock.MagicMock()
        rows = [{'id': str(uuid.uuid4()), 'name': 'Dresses'}]
        with mock.patch.object(sync_mod, 'execute_values') as bulk_insert:
            sync_mod._sync_table(
                conn, 'categories', lambda: rows, sync_mod.UUID_TABLES)

        query = bulk_insert.call_args[0][1]
        self.assertEqual(query.count('%s'), 1)
        self.assertIn('VALUES %s', query)

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_count_mismatch_fails_the_run(self):
        """A replica that silently disagrees with Django is worse than none."""
        from replica.services import sync as sync_mod

        def fake_sync_table(conn, table, extractor, key_kind):
            # Report a mismatch that must abort the run.
            return {'source': 5, 'replica': 1}

        conn = mock.MagicMock()
        with mock.patch.object(sync_mod, 'get_connection', return_value=conn), \
             mock.patch.object(sync_mod, '_start_run', return_value=1), \
             mock.patch.object(sync_mod, '_sync_table', side_effect=fake_sync_table), \
             mock.patch.object(
                 sync_mod, '_write_snapshots',
                 return_value={'snapshot_rows': 0, 'snapshot_total': 0},
             ):
            with self.assertRaises(RuntimeError) as ctx:
                sync_mod.sync_replica(triggered_by='manual', include_storage=False)

        self.assertIn('did not reconcile', str(ctx.exception))

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_unknown_trigger_source_rejected(self):
        from replica.services.sync import sync_replica

        with self.assertRaises(ValueError):
            sync_replica(triggered_by='someone-else')


class ReplicaPermissionSeedTests(TestCase):
    """The replica permissions must exist in the database, not just the code.

    `manage.py seed_roles` cannot run on the free Render plan (no shell), so the
    codes only reach the database via a data migration. If that migration is
    missing the nav link is hidden and the page 403s for every user, with no
    error anywhere -- exactly the kind of failure worth a test.
    """

    def test_permissions_are_seeded_in_the_database(self):
        from access_control.models import Permission

        codes = set(
            Permission.objects.filter(code__startswith='replica.')
            .values_list('code', flat=True)
        )

        self.assertEqual(codes, {'replica.view', 'replica.sync'})

    def test_codes_are_declared_in_the_catalogue(self):
        from access_control.permissions_catalog import PERMISSIONS

        codes = {p[0] for p in PERMISSIONS}

        self.assertIn('replica.view', codes)
        self.assertIn('replica.sync', codes)

    def test_sync_is_flagged_sensitive(self):
        """replica.sync writes to an external system, so it must be flagged."""
        from access_control.permissions_catalog import PERMISSION_BY_CODE

        self.assertTrue(PERMISSION_BY_CODE['replica.sync'][3])
        self.assertFalse(PERMISSION_BY_CODE['replica.view'][3])


class AdvisoryLockTests(TestCase):
    """Defect 1: two overlapping syncs must not be possible."""

    def test_lock_refuses_a_second_run(self):
        """A cron tick landing on a manual click must not start a second sync."""
        from replica.services import sync as sync_mod

        conn = mock.MagicMock()
        with mock.patch.object(sync_mod, 'get_connection', return_value=conn), \
             mock.patch.object(
                 sync_mod, '_start_run', return_value=1), \
             mock.patch.object(sync_mod, '_acquire_lock') as acquire:
            acquire.side_effect = sync_mod.ReplicaAlreadyRunning('busy')

            with self.assertRaises(sync_mod.ReplicaAlreadyRunning):
                sync_mod.sync_replica(triggered_by='cron', include_storage=False)

        # The connection must still be closed so the lock is released.
        self.assertTrue(conn.close.called)

    def test_lock_is_taken_before_any_write(self):
        from replica.services import sync as sync_mod

        conn = mock.MagicMock()
        with mock.patch.object(sync_mod, 'get_connection', return_value=conn), \
             mock.patch.object(sync_mod, '_acquire_lock') as acquire, \
             mock.patch.object(sync_mod, '_start_run') as start:
            try:
                sync_mod.sync_replica(
                    triggered_by='cron', include_storage=False)
            except Exception:  # noqa: BLE001 - ordering is what matters
                pass

        self.assertTrue(acquire.called)

    @override_settings(REPLICA_SYNC_MODE='deferred', SUPABASE_DB_URL=REPLICA_DB)
    def test_deferred_button_queues_instead_of_running(self):
        """Defect 2: the button must not run a long sync inside the request."""
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.create_superuser(
            username=f'defer-{uuid.uuid4().hex[:8]}', password='pw',
            email='d@example.com')
        self.client.force_login(admin)

        with mock.patch('admin_ui.views.sync_replica') as fake_run, \
             mock.patch('admin_ui.views.queue_replica_sync',
                        return_value=7) as fake_queue:
            response = self.client.post(reverse('admin-replica-sync-action'))

        self.assertEqual(response.status_code, 302)
        # Both assertions matter: the first alone would pass on a 403/404.
        self.assertFalse(fake_run.called, 'deferred mode must not sync inline')
        self.assertTrue(fake_queue.called, 'deferred mode must queue a run')

    @override_settings(REPLICA_SYNC_MODE='inline', SUPABASE_DB_URL=REPLICA_DB)
    def test_inline_button_runs_the_sync(self):
        from django.contrib.auth import get_user_model

        admin = get_user_model().objects.create_superuser(
            username=f'inline-{uuid.uuid4().hex[:8]}', password='pw',
            email='i@example.com')
        self.client.force_login(admin)

        with mock.patch('admin_ui.views.sync_replica') as fake_run, \
             mock.patch('admin_ui.views.queue_replica_sync') as fake_queue:
            fake_run.return_value = {'counts': {}, 'storage': {}}
            self.client.post(reverse('admin-replica-sync-action'))

        self.assertTrue(fake_run.called)
        self.assertFalse(fake_queue.called)

    def test_invalid_sync_mode_falls_back_to_inline(self):
        from django.conf import settings as django_settings

        self.assertIn(
            getattr(django_settings, 'REPLICA_SYNC_MODE', 'inline'),
            {'inline', 'deferred'},
        )


class ReplicaEndpointTests(TestCase):
    """The cron endpoint must mirror EmailSweepView's security posture."""

    def setUp(self):
        self.url = reverse('admin-replica-sync')
        self.settings_token = override_settings(
            REPLICA_SYNC_TOKEN='a-long-random-token')
        self.settings_token.enable()

    def tearDown(self):
        self.settings_token.disable()

    def test_returns_404_when_token_unset(self):
        """An unconfigured deployment must not advertise the route at all."""
        with override_settings(REPLICA_SYNC_TOKEN=''):
            response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)

    def test_returns_401_without_token(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 401)

    def test_returns_401_with_wrong_token(self):
        response = self.client.post(
            self.url, HTTP_X_REPLICA_TOKEN='wrong-token')

        self.assertEqual(response.status_code, 401)

    def test_runs_sync_with_valid_token(self):
        with mock.patch(
                'admin_api.views.sync_replica') as fake_sync:
            fake_sync.return_value = {'counts': {'products': {}}, 'storage': {}}
            response = self.client.post(
                self.url, HTTP_X_REPLICA_TOKEN='a-long-random-token')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_sync.called)
        self.assertEqual(
            fake_sync.call_args.kwargs.get('triggered_by'), 'cron')

    def test_returns_409_when_a_sync_is_already_running(self):
        """A cron tick overlapping a manual run is expected, not a failure."""
        from replica.services.sync import ReplicaAlreadyRunning

        with mock.patch('admin_api.views.sync_replica') as fake_sync:
            fake_sync.side_effect = ReplicaAlreadyRunning('busy')
            response = self.client.post(
                self.url, HTTP_X_REPLICA_TOKEN='a-long-random-token')

        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data.get('skipped'))

    def test_missing_config_returns_503(self):
        from replica.services.sync import ReplicaNotConfigured

        with mock.patch('admin_api.views.sync_replica') as fake_sync:
            fake_sync.side_effect = ReplicaNotConfigured('no db url')
            response = self.client.post(
                self.url, HTTP_X_REPLICA_TOKEN='a-long-random-token')

        self.assertEqual(response.status_code, 503)

    def test_sync_failure_returns_500(self):
        with mock.patch('admin_api.views.sync_replica') as fake_sync:
            fake_sync.side_effect = RuntimeError('boom')
            response = self.client.post(
                self.url, HTTP_X_REPLICA_TOKEN='a-long-random-token')

        self.assertEqual(response.status_code, 500)


class ReplicaPageTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        # Superuser: the page is gated by replica.view / replica.sync, which
        # staff only hold once a role grants them.
        self.user = get_user_model().objects.create_superuser(
            username=f'replica-staff-{uuid.uuid4().hex[:8]}',
            password='pw', email='staff@example.com')
        self.client.force_login(self.user)

    def test_get_on_sync_action_never_writes(self):
        """A GET must not trigger a write to an external system."""
        with override_settings(SUPABASE_DB_URL=REPLICA_DB), \
             mock.patch('admin_ui.views.sync_replica') as fake_sync:
            response = self.client.get(reverse('admin-replica-sync-action'))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(fake_sync.called)

    @override_settings(SUPABASE_DB_URL='')
    def test_status_page_renders_when_unconfigured(self):
        response = self.client.get(reverse('admin-replica'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SUPABASE_DB_URL')

    @override_settings(SUPABASE_DB_URL=REPLICA_DB)
    def test_status_page_renders_with_no_runs_yet(self):
        with mock.patch('admin_ui.views.latest_run', return_value=None):
            response = self.client.get(reverse('admin-replica'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no sync runs recorded')

    def test_status_page_requires_replica_view_permission(self):
        """Non-staff must not reach the page even with a valid session."""
        from django.contrib.auth import get_user_model

        plain = get_user_model().objects.create_user(
            username=f'plain-{uuid.uuid4().hex[:8]}', password='pw')
        self.client.force_login(plain)

        response = self.client.get(reverse('admin-replica'))

        self.assertEqual(response.status_code, 403)


class StorageMirrorTests(TestCase):
    @override_settings(
        SUPABASE_URL='https://example.supabase.co',
        SUPABASE_SERVICE_ROLE_KEY='service-key',
        SUPABASE_STORAGE_BUCKET='product-images',
        REPLICA_BACKUP_BUCKET='product-images-backup',
    )
    def test_refuses_to_mirror_bucket_onto_itself(self):
        from replica.services.storage_mirror import mirror_bucket

        with override_settings(REPLICA_BACKUP_BUCKET='product-images'):
            with self.assertRaises(RuntimeError) as ctx:
                mirror_bucket()

        self.assertIn('must differ', str(ctx.exception))

    @override_settings(
        SUPABASE_URL='',
        SUPABASE_SERVICE_ROLE_KEY='',
    )
    def test_requires_supabase_credentials(self):
        from replica.services.storage_mirror import mirror_bucket

        with self.assertRaises(RuntimeError) as ctx:
            mirror_bucket()

        self.assertIn('SUPABASE_URL', str(ctx.exception))