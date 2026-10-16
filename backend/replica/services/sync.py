"""Mirror the Django system of record into the Supabase ``replica`` schema.

Why a direct Postgres connection rather than PostgREST: PostgREST only serves
schemas listed in Supabase's ``db-schemas`` setting (default ``public``). That
is precisely why the replica lives in its own schema -- it must stay
unreachable from the anon key baked into the public Vite bundle -- so the REST
API cannot be used to write it. ``SUPABASE_DB_URL`` is the direct connection
string from Dashboard -> Project Settings -> Database.

Design notes
------------
* **Upsert, never truncate.** The catalogue snapshot history has to survive, so
  a truncate-and-reload strategy is not usable here. Each table is upserted,
  then rows that vanished in Django are deleted.
* **One transaction per table.** A failure mid-run rolls that table back to its
  previous contents instead of leaving it empty. A partially-empty replica is
  worse than a stale one.
* **Reconciliation.** Django counts are compared against Supabase counts after
  every run and a mismatch fails the run loudly. A replica you cannot trust is
  worse than no replica.
"""

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

import psycopg2
from django.conf import settings
from django.db.models import Count, Max, Min, Q, Sum
from psycopg2.extras import Json, execute_values

from audit.models import AuditLog
from audit.sanitizers import sanitize
from catalog.models import Category, Product, ProductVariant
from inventory.models import InventoryTransaction, StockReservation
from orders.models import Order, OrderItem
from payments.models import PaymentIntent
from promotions.models import Promotion, PromotionRedemption
from receipts.models import Receipt

logger = logging.getLogger(__name__)




class ReplicaNotConfigured(RuntimeError):
    """SUPABASE_DB_URL is missing, so there is nowhere to write the replica."""


class ReplicaAlreadyRunning(RuntimeError):
    """Another sync holds the advisory lock.

    Raised instead of letting two syncs overlap. Without this, a cron run and a
    manual click can interleave -- and because the admin button runs the sync
    inside the HTTP request, an operator who retries after a proxy timeout
    starts a *second* full sync while the first is still going.
    """


class ReplicaStatusUnavailable(RuntimeError):
    """The replica could not be queried for its most recent run."""


# Session-level advisory lock, namespaced so it cannot collide with anything
# else the database does. Taken on the connection that does the work and held
# until that connection closes, so a crashed run releases it automatically.
_LOCK_KEY = "modeza_replica_sync"


def replica_configured():
    return bool(getattr(settings, 'SUPABASE_DB_URL', '').strip())


def get_connection():
    if not replica_configured():
        raise ReplicaNotConfigured(
            'SUPABASE_DB_URL is not configured. Set it to the direct Postgres '
            'connection string from Supabase Dashboard -> Project Settings -> '
            'Database, then redeploy.'
        )
    # No dbname override: the Supabase default database is "postgres" and is
    # already embedded in the connection string.
    return psycopg2.connect(settings.SUPABASE_DB_URL)


# ---------------------------------------------------------------------------
# Row extractors -- Django -> plain dicts matching the replica columns.
# ---------------------------------------------------------------------------

def _dt(value):
    return value.isoformat() if value else None


def _supabase_profile_id(username):
    """Return the Supabase auth UUID encoded in our local username, if any."""
    prefix = 'supabase_'
    if not isinstance(username, str) or not username.startswith(prefix):
        return None
    try:
        return str(UUID(username[len(prefix):]))
    except ValueError:
        return None


def category_rows():
    return [
        {
            'id': str(c.id), 'name': c.name, 'slug': c.slug,
            'description': c.description, 'image_url': c.image_url,
            'is_active': c.is_active,
            'created_at': _dt(c.created_at), 'updated_at': _dt(c.updated_at),
        }
        for c in Category.objects.all()
    ]


def product_rows():
    return [
        {
            'id': str(p.id), 'category_id': str(p.category_id), 'name': p.name,
            'slug': p.slug, 'tagline': p.tagline, 'description': p.description,
            'details': p.details, 'price_minor': p.price_minor,
            'compare_at_price_minor': p.compare_at_price_minor,
            'images': p.images, 'status': p.status,
            'is_featured': p.is_featured, 'is_new_arrival': p.is_new_arrival,
            'is_best_seller': p.is_best_seller, 'sku': p.sku,
            'product_code': p.product_code, 'stock_quantity': p.stock_quantity,
            'created_at': _dt(p.created_at), 'updated_at': _dt(p.updated_at),
        }
        for p in Product.objects.all()
    ]


def variant_rows():
    return [
        {
            'id': str(v.id), 'product_id': str(v.product_id), 'sku': v.sku,
            'size': v.size, 'color': v.color, 'color_hex': v.color_hex,
            'price_minor': v.price_minor, 'stock_quantity': v.stock_quantity,
            'is_active': v.is_active,
        }
        for v in ProductVariant.objects.all()
    ]


def order_rows():
    return [
        {
            'id': str(o.id), 'order_number': o.order_number,
            'user_id': _supabase_profile_id(o.user.username) if o.user else None,
            'customer': o.customer, 'notes': o.notes,
            'subtotal_minor': o.subtotal_minor, 'discount_minor': o.discount_minor,
            'shipping_cost_minor': o.shipping_cost_minor,
            'shipping_discount_minor': o.shipping_discount_minor,
            'tax_minor': o.tax_minor, 'total_minor': o.total_minor,
            'coupon_code': o.coupon_code,
            'promotion_snapshot': o.promotion_snapshot,
            'shipping_method': o.shipping_method,
            'payment_method': o.payment_method, 'status': o.status,
            'payment_status': o.payment_status, 'currency': o.currency,
            'created_at': _dt(o.created_at), 'updated_at': _dt(o.updated_at),
        }
        for o in Order.objects.select_related('user').all()
    ]


def order_item_rows():
    return [
        {
            'id': str(i.id), 'order_id': str(i.order_id),
            'product_id': str(i.product_id) if i.product_id else None,
            'variant_id': str(i.variant_id) if i.variant_id else None,
            'product_name': i.product_name, 'variant_sku': i.variant_sku,
            'variant_size': i.variant_size, 'variant_color': i.variant_color,
            'image_url': i.image_url, 'unit_price_minor': i.unit_price_minor,
            'quantity': i.quantity, 'line_total_minor': i.line_total_minor,
        }
        for i in OrderItem.objects.all()
    ]


def payment_intent_rows():
    # Provider identifiers and customer phone details stay out of the analytics replica.
    return [
        {
            'id': p.id, 'order_id': str(p.order_id),
            'amount_minor': p.amount_minor, 'currency': p.currency,
            'method': p.method, 'status': p.status,
            'gateway_reference': p.gateway_reference, 'metadata': p.metadata,
            'created_at': _dt(p.created_at), 'updated_at': _dt(p.updated_at),
        }
        for p in PaymentIntent.objects.all()
    ]


def inventory_transaction_rows():
    return [
        {
            'id': str(t.id), 'variant_id': str(t.variant_id),
            'quantity_delta': t.quantity_delta,
            'previous_quantity': t.previous_quantity,
            'new_quantity': t.new_quantity, 'reason': t.reason,
            'order_id': str(t.order_id) if t.order_id else None,
            'actor_id': _supabase_profile_id(t.actor.username)
            if t.actor else None,
            'created_at': _dt(t.created_at),
        }
        for t in InventoryTransaction.objects.select_related('actor').all()
    ]


def stock_reservation_rows():
    return [
        {
            'id': str(r.id), 'order_id': str(r.order_id),
            'variant_id': str(r.variant_id), 'quantity': r.quantity,
            'status': r.status, 'expires_at': _dt(r.expires_at),
            'created_at': _dt(r.created_at), 'released_at': _dt(r.released_at),
        }
        for r in StockReservation.objects.all()
    ]


def promotion_rows():
    return [
        {
            'id': str(p.id), 'name': p.name, 'description': p.description,
            'promotion_type': p.promotion_type, 'status': p.status,
            'discount_percent': float(p.discount_percent),
            'discount_amount_minor': p.discount_amount_minor,
            'maximum_discount_minor': p.maximum_discount_minor,
            'minimum_order_value_minor': p.minimum_order_value_minor,
            'minimum_quantity': p.minimum_quantity,
            'qualifying_quantity': p.qualifying_quantity,
            'reward_quantity': p.reward_quantity,
            'reward_discount_percent': float(p.reward_discount_percent),
            'coupon_code': p.coupon_code, 'is_automatic': p.is_automatic,
            'starts_at': _dt(p.starts_at), 'ends_at': _dt(p.ends_at),
            'usage_limit': p.usage_limit,
            'usage_limit_per_customer': p.usage_limit_per_customer,
            'priority': p.priority, 'stackable': p.stackable,
            'customer_scope': p.customer_scope,
            'created_at': _dt(p.created_at), 'updated_at': _dt(p.updated_at),
        }
        for p in Promotion.objects.all()
    ]


def promotion_redemption_rows():
    return [
        {
            'id': str(r.id), 'promotion_id': str(r.promotion_id),
            'order_id': str(r.order_id),
            'user_id': _supabase_profile_id(r.user.username) if r.user else None,
            'coupon_code': r.coupon_code, 'discount_minor': r.discount_minor,
            'shipping_discount_minor': r.shipping_discount_minor,
            'voided': r.voided, 'redeemed_at': _dt(r.redeemed_at),
        }
        for r in PromotionRedemption.objects.select_related('user').all()
    ]


def receipt_rows():
    return [
        {
            'id': str(r.id), 'order_id': str(r.order_id),
            'receipt_number': r.receipt_number, 'status': r.status,
            'snapshot': r.snapshot, 'pdf_url': r.pdf_url,
            'amount_minor': r.amount_minor, 'currency': r.currency,
            'gateway_reference': r.gateway_reference,
            'generated_at': _dt(r.generated_at),
            'created_at': _dt(r.created_at), 'updated_at': _dt(r.updated_at),
        }
        for r in Receipt.objects.all()
    ]


def audit_log_rows():
    """Export useful audit events without duplicating direct PII fields."""
    return [
        {
            'id': str(log.id),
            'actor_id': (
                _supabase_profile_id(log.actor.username) if log.actor else None
            ),
            'actor_role': log.actor_role,
            'action': log.action,
            'category': log.category,
            'object_type': log.object_type,
            'object_id': log.object_id,
            'metadata': sanitize(log.metadata or {}),
            'result': log.result,
            'severity': log.severity,
            'request_id': log.request_id,
            'path': log.path,
            'status_code': log.status_code,
            'created_at': _dt(log.created_at),
        }
        for log in AuditLog.objects.select_related('actor').all()
    ]


def customer_rows():
    """Aggregate per-customer spend.

    Cancelled orders are excluded from ``total_spent_minor`` but still counted
    in ``order_count``, so cancellation rate stays visible without skewing
    revenue. No identity fields -- those resolve via public.profiles.
    """
    rows = (
        Order.objects.filter(user_id__isnull=False)
        .values('user_id')
        .annotate(
            first_order_at=Min('created_at'),
            last_order_at=Max('created_at'),
            order_count=Count('id'),
            total_spent_minor=Sum(
                'total_minor',
                filter=Q(status__in=[
                    Order.Status.CONFIRMED, Order.Status.PROCESSING,
                    Order.Status.SHIPPED, Order.Status.DELIVERED,
                    Order.Status.RECEIVED,
                ]),
            ),
        )
    )
    aggregates = list(rows)
    if not aggregates:
        return []

    from django.contrib.auth import get_user_model

    users = get_user_model().objects.filter(
        pk__in=[row['user_id'] for row in aggregates]
    ).values_list('pk', 'username')
    profile_ids = {
        user_id: profile_id
        for user_id, username in users
        if (profile_id := _supabase_profile_id(username)) is not None
    }

    return [
        {
            'user_id': profile_ids[r['user_id']],
            'first_order_at': _dt(r['first_order_at']),
            'last_order_at': _dt(r['last_order_at']),
            'order_count': r['order_count'],
            'total_spent_minor': int(r['total_spent_minor'] or 0),
        }
        for r in aggregates if r['user_id'] in profile_ids
    ]


# Ordered so foreign keys land before the rows that reference them.
# Each entry: (table_name, extractor_fn, key_column, key_is_uuid).
TABLE_SPECS = [
    ('categories',              category_rows,              'id',      True),
    ('products',                product_rows,               'id',      True),
    ('product_variants',        variant_rows,               'id',      True),
    ('orders',                  order_rows,                 'id',      True),
    ('order_items',             order_item_rows,            'id',      True),
    ('payment_intents',         payment_intent_rows,        'id',      False),
    ('inventory_transactions',  inventory_transaction_rows, 'id',      True),
    ('stock_reservations',      stock_reservation_rows,     'id',      True),
    ('promotions',              promotion_rows,             'id',      True),
    ('promotion_redemptions',   promotion_redemption_rows,  'id',      True),
    ('receipts',                receipt_rows,               'id',      True),
    ('audit_logs',              audit_log_rows,              'id',      True),
    ('customers',               customer_rows,              'user_id', True),
]


def current_row_counts():
    """Compare current Django rows with the replica without modifying either.

    Unlike the counts stored on the last sync run, these values are calculated
    on every status-page request so new or removed Django records appear as a
    drift before the next backup is run.
    """
    from django.contrib.auth import get_user_model

    conn = None
    try:
        source_counts = {
            'categories': Category.objects.count(),
            'products': Product.objects.count(),
            'product_variants': ProductVariant.objects.count(),
            'orders': Order.objects.count(),
            'order_items': OrderItem.objects.count(),
            'payment_intents': PaymentIntent.objects.count(),
            'inventory_transactions': InventoryTransaction.objects.count(),
            'stock_reservations': StockReservation.objects.count(),
            'promotions': Promotion.objects.count(),
            'promotion_redemptions': PromotionRedemption.objects.count(),
            'receipts': Receipt.objects.count(),
            'audit_logs': AuditLog.objects.count(),
        }
        linked_usernames = get_user_model().objects.filter(
            pk__in=Order.objects.filter(user_id__isnull=False)
            .values_list('user_id', flat=True)
        ).values_list('username', flat=True)
        source_counts['customers'] = sum(
            _supabase_profile_id(username) is not None
            for username in linked_usernames
        )

        conn = get_connection()
        counts = {}
        with conn.cursor() as cur:
            for table, _extractor, _key_col, _key_is_uuid in TABLE_SPECS:
                cur.execute(f'SELECT count(*) FROM replica.{table}')
                replica_count = cur.fetchone()[0]
                counts[table] = {
                    'source': source_counts[table],
                    'replica': replica_count,
                }
        return counts
    except Exception as exc:  # noqa: BLE001 - status page renders degraded state
        logger.warning('Live replica row-count comparison failed.', exc_info=True)
        raise ReplicaStatusUnavailable(
            'Could not compare current Django and Supabase row counts.'
        ) from exc
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_JSONB_COLUMNS = {
    'details', 'images', 'customer', 'promotion_snapshot', 'metadata',
    'snapshot', 'table_counts', 'storage', 'payload',
}


def _adapter(value, column):
    """psycopg2 needs explicit adapters for jsonb; datetimes and decimals too."""
    if column in _JSONB_COLUMNS and value is not None:
        return Json(value)
    return value


def _sync_table(conn, table, extractor, key_col, key_is_uuid):
    """Upsert one table and delete rows that vanished in Django.

    Commits on success, rolls back on any error -- so a failure leaves this
    table exactly as it was rather than half-written.
    """
    rows = extractor()
    columns = list(rows[0].keys()) if rows else []

    try:
        with conn.cursor() as cur:
            if rows:
                updates = ', '.join(
                    f'{c} = EXCLUDED.{c}' for c in columns if c != key_col
                )
                sql = (
                    f'INSERT INTO replica.{table} ({", ".join(columns)}) '
                    f'VALUES %s '
                    f'ON CONFLICT ({key_col}) DO UPDATE SET {updates}'
                )
                values = [
                    tuple(_adapter(row[c], c) for c in columns) for row in rows
                ]
                execute_values(cur, sql, values, page_size=500)

                # Drop replica rows whose Django counterpart is gone.
                ids = [row[key_col] for row in rows]
                array_cast = 'uuid[]' if key_is_uuid else 'text[]'
                cur.execute(
                    f'DELETE FROM replica.{table} t '
                    f'WHERE NOT EXISTS '
                    f'(SELECT 1 FROM unnest(%s::{array_cast}) v '
                    f'WHERE v = t.{key_col})',
                    (ids,),
                )
            else:
                # Django has no rows at all: clear the replica table rather than
                # leaving orphaned data behind.
                cur.execute(f'DELETE FROM replica.{table}')

            cur.execute(f'SELECT count(*) FROM replica.{table}')
            replica_count = cur.fetchone()[0]

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {'source': len(rows), 'replica': replica_count}


def _write_snapshots(conn):
    """Append today's catalogue snapshot. Idempotent per day."""
    today = datetime.now(timezone.utc).date()
    payload = []
    for entity, rows in (
        ('product', product_rows()),
        ('variant', variant_rows()),
        ('category', category_rows()),
    ):
        for row in rows:
            payload.append((entity, row['id'], today, json.dumps(row, default=str)))

    with conn.cursor() as cur:
        if payload:
            execute_values(
                cur,
                'INSERT INTO replica.catalogue_snapshots '
                '(entity, entity_id, snapshot_date, payload) '
                'VALUES %s '
                'ON CONFLICT (entity, entity_id, snapshot_date) '
                'DO UPDATE SET payload = EXCLUDED.payload, '
                'synced_at = now()',
                payload,
                template='(%s, %s, %s, %s::jsonb)',
            )
        cur.execute('SELECT count(*) FROM replica.catalogue_snapshots')
        total = cur.fetchone()[0]
    conn.commit()
    return {'snapshot_rows': len(payload), 'snapshot_total': total}


def _acquire_lock(conn):
    """Take the advisory lock, or raise :class:`ReplicaAlreadyRunning`."""
    with conn.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(hashtext(%s))', (_LOCK_KEY,))
        if not cur.fetchone()[0]:
            raise ReplicaAlreadyRunning(
                'A replica sync is already running. Wait for it to finish '
                'before starting another.'
            )


def _start_run(conn, triggered_by, status='running'):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO replica.sync_runs (triggered_by, status) '
            'VALUES (%s, %s) RETURNING id',
            (triggered_by, status),
        )
        return cur.fetchone()[0]


def _finish_run(conn, run_id, status, counts, storage_info=None, error=None):
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE replica.sync_runs SET finished_at = now(), status = %s, '
            'table_counts = %s, storage = %s, error = %s WHERE id = %s',
            (status, Json(counts), Json(storage_info or {}), error, run_id),
        )
    conn.commit()


def latest_run():
    """Return the most recent run, or ``None`` when no run has been recorded."""
    if not replica_configured():
        return None
    try:
        conn = get_connection()
    except Exception as exc:  # noqa: BLE001 - status page renders degraded state
        logger.warning('Replica status unavailable: cannot connect.', exc_info=True)
        raise ReplicaStatusUnavailable(
            'Could not connect to the replica database.'
        ) from exc
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, started_at, finished_at, status, triggered_by, '
                'table_counts, storage, error FROM replica.sync_runs '
                'ORDER BY started_at DESC LIMIT 1'
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            'id': row[0], 'started_at': row[1], 'finished_at': row[2],
            'status': row[3], 'triggered_by': row[4],
            'table_counts': row[5] or {}, 'storage': row[6] or {},
            'error': row[7],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning('Replica status query failed.', exc_info=True)
        raise ReplicaStatusUnavailable(
            'Could not read replica sync history.'
        ) from exc
    finally:
        conn.close()


def queue_replica_sync(triggered_by='manual'):
    """Record a request to run the replica, for ``REPLICA_SYNC_MODE=deferred``.

    Returns the new ``sync_runs`` id. The row is written with status
    ``requested`` and no ``finished_at``; the cron picks it up on its next
    pass. Nothing is written to the replica itself here, so this is safe to
    call from a web request that might time out.
    """
    if not replica_configured():
        raise ReplicaNotConfigured(
            'SUPABASE_DB_URL is not configured; the replica is unreachable.'
        )
    conn = get_connection()
    try:
        run_id = _start_run(conn, triggered_by, status='requested')
        conn.commit()
        return run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def pending_request():
    """The newest ``requested`` run that no completed run has superseded.

    A request counts as satisfied once a run *started* after it finishes, so
    the page stops showing "queued" as soon as the cron picks it up.
    """
    if not replica_configured():
        return None
    try:
        conn = get_connection()
    except Exception:  # noqa: BLE001
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, started_at, triggered_by FROM replica.sync_runs "
                "WHERE status = 'requested' "
                "  AND id > COALESCE((SELECT MAX(id) FROM replica.sync_runs "
                "                   WHERE status <> 'requested'), 0) "
                "ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        if not row:
            return None
        return {'id': row[0], 'started_at': row[1], 'triggered_by': row[2]}
    except Exception:  # noqa: BLE001
        logger.warning('Pending-request query failed.', exc_info=True)
        return None
    finally:
        conn.close()


def sync_replica(triggered_by='manual', include_storage=True):
    """Run a full replica sync. Returns a summary dict.

    Raises ``ReplicaNotConfigured`` when ``SUPABASE_DB_URL`` is unset,
    ``ReplicaAlreadyRunning`` when another sync holds the advisory lock, and
    ``RuntimeError`` when the row counts do not reconcile.
    """
    if triggered_by not in {'cron', 'manual', 'first'}:
        raise ValueError(f'Unknown triggered_by: {triggered_by!r}')

    counts, storage_info = {}, {}
    run_id = None
    conn = get_connection()
    try:
        _acquire_lock(conn)

        try:
            run_id = _start_run(conn, triggered_by)
            conn.commit()
        except Exception:  # noqa: BLE001 - replica may not exist yet
            conn.rollback()
            logger.warning('Could not open a sync_runs row.', exc_info=True)

        for table, extractor, key_col, key_is_uuid in TABLE_SPECS:
            counts[table] = _sync_table(conn, table, extractor,
                                        key_col, key_is_uuid)

        counts.update(_write_snapshots(conn))

        mismatches = [
            f'{t}: django={v["source"]} supabase={v["replica"]}'
            for t, v in counts.items()
            if isinstance(v, dict)
            and 'source' in v
            and v['source'] != v['replica']
        ]

        if mismatches:
            raise RuntimeError(
                'Row counts did not reconcile: ' + '; '.join(mismatches)
            )

        if include_storage:
            from replica.services.storage_mirror import mirror_bucket
            try:
                storage_info = mirror_bucket()
            except Exception as exc:  # noqa: BLE001
                # Images are mirrored separately from the relational replica;
                # losing them must not invalidate a good data sync.
                storage_info = {'status': 'failed', 'error': str(exc)}
                logger.warning('Storage mirror failed.', exc_info=True)

        if run_id is not None:
            _finish_run(conn, run_id, 'success', counts, storage_info)

        return {
            'status': 'success',
            'counts': counts,
            'storage': storage_info,
            'started_by': triggered_by,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception('Replica sync failed.')
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - the connection may already be lost
            logger.warning('Could not roll back failed replica sync.', exc_info=True)
        if run_id is not None:
            try:
                _finish_run(conn, run_id, 'failure', counts, None, str(exc)[:2000])
            except Exception:  # noqa: BLE001
                logger.warning('Could not record sync failure.', exc_info=True)
        raise
    finally:
        conn.close()
