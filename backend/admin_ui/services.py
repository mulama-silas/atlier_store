"""Admin notification service — audit-linked, never-raising notifications.

Modeza's notification budget is log-first, notify-second:

* an :class:`audit.models.AuditLog` row is always written for the underlying
  event (the authoritative record) before any notification is produced,
* :class:`AdminNotificationService.notify` links the notification to that row
  (``audit_log`` FK plus denormalised event_type/severity/actor/resource/
  request_id so the admin UI never has to join through to audit rows), and
* writes are deferred with ``transaction.on_commit`` inside atomic blocks so a
  rolled-back business operation never leaves orphan notifications, and they
  can never bring the business operation down (``never raises``).

Deduplication is per ``(recipient, event_key)``; call sites that already emit
a notification (e.g. the Order/ProductVariant post_save signals) share the
same ``event_key`` strings so a notification is produced exactly once.
"""

import logging

from django.db import connection, transaction

from audit.sanitizers import sanitize
from audit.services import AuditLogService

from .models import AdminNotification, notify_staff

logger = logging.getLogger("admin_ui.notify")

# Canonical audit action -> notification display metadata. Only meaningful
# successes/failures are included; high-frequency browse events (product_viewed,
# search_performed, cart_item_added, wishlist_item_added, ...) intentionally
# stay audit-only so the admin bell is not drowned in noise.
AUTO_NOTIFY = {
    'signup':                 {'category': 'customer', 'severity': 'info',
                               'title': 'New customer registered'},
    'registration_failed':    {'category': 'customer', 'severity': 'medium',
                               'title': 'Registration failed'},
    'order_created':          {'category': 'order', 'severity': 'info',
                               'title': 'Order placed'},
    'order_creation_failed':  {'category': 'order', 'severity': 'medium',
                               'title': 'Order creation failed'},
    'order_cancelled':        {'category': 'order', 'severity': 'medium',
                               'title': 'Order cancelled'},
    'order_confirmed':        {'category': 'order', 'severity': 'info',
                               'title': 'Order confirmed'},
    'order_received':         {'category': 'order', 'severity': 'info',
                               'title': 'Order received'},
    'checkout_failed':        {'category': 'order', 'severity': 'medium',
                               'title': 'Checkout failed'},
    'payment_success':        {'category': 'payment', 'severity': 'info',
                               'title': 'Payment received'},
    'payment_failed':         {'category': 'payment', 'severity': 'medium',
                               'title': 'Payment failed'},
    'payment_initiation_failed': {'category': 'payment', 'severity': 'medium',
                                  'title': 'Payment initiation failed'},
    'payment_timeout':        {'category': 'payment', 'severity': 'medium',
                               'title': 'Payment timed out'},
    'payment_reversed':       {'category': 'payment', 'severity': 'high',
                               'title': 'Payment reversed'},
    'receipt_generated':      {'category': 'payment', 'severity': 'info',
                               'title': 'Receipt issued'},
    'receipt_generation_failed': {'category': 'payment', 'severity': 'high',
                                  'title': 'Receipt generation failed'},
    'receipt_regenerated':    {'category': 'payment', 'severity': 'info',
                               'title': 'Receipt regenerated'},
    'refund':                 {'category': 'payment', 'severity': 'medium',
                               'title': 'Refund processed'},
    'refund_requested':       {'category': 'payment', 'severity': 'medium',
                               'title': 'Refund requested'},
    'refund_completed':       {'category': 'payment', 'severity': 'medium',
                               'title': 'Refund processed'},
    'cart_add_failed':        {'category': 'order', 'severity': 'medium',
                               'title': 'Cart add failed'},
    'cart_update_failed':     {'category': 'order', 'severity': 'medium',
                               'title': 'Cart update failed'},
    'rate_limit_exceeded':    {'category': 'system', 'severity': 'medium',
                               'title': 'Rate limit exceeded'},
    'unexpected_server_error': {'category': 'system', 'severity': 'high',
                                'title': 'Unexpected server error'},
    'server_error':           {'category': 'system', 'severity': 'high',
                               'title': 'Server error'},
    'permission_denied':      {'category': 'security', 'severity': 'medium',
                               'title': 'Permission denied'},
    'access_denied':          {'category': 'security', 'severity': 'critical',
                               'title': 'Access denied'},
    'security_event':         {'category': 'security', 'severity': 'high',
                               'title': 'Security event'},
    'inventory_low_stock':    {'category': 'inventory', 'severity': 'medium',
                               'title': 'Low stock alert'},
}

# Events the browser may report where the client is the only possible source
# AND the success/failure is important enough to notify admins about. Successful
# signup notifications are emitted when the authenticated Supabase identity is
# provisioned locally, which also covers email-confirmation signup flows where
# the browser has no session to report with.
CLIENT_NOTIFY_ALLOW = {'registration_failed'}


class AdminNotificationService:
    """Central writer of admin notifications, mirroring AuditLogService."""

    @classmethod
    def notify(cls, category, title, message, *, link='', event_key='',
               event_type='', severity='info', audit_log=None, recipient=None,
               actor=None, resource_type=None, resource_id=None,
               request_id='', metadata=None):
        """Create admin notifications for an audited event.

        Fields not explicitly provided are derived from ``audit_log`` when one
        is present (event_type/severity/actor/resource/request_id). Writes are
        deferred to ``transaction.on_commit`` inside atomic blocks so they never
        survive a rollback, and this method never raises.
        """
        try:
            prepared = cls._prepare(
                category=category, title=title, message=message, link=link,
                event_key=event_key, event_type=event_type, severity=severity,
                audit_log=audit_log, recipient=recipient, actor=actor,
                resource_type=resource_type, resource_id=resource_id,
                request_id=request_id, metadata=metadata,
            )
            if connection.in_atomic_block and not connection.needs_rollback:
                transaction.on_commit(lambda: _create_notifications(**prepared))
                return []
            return _create_notifications(**prepared)
        except Exception:
            logger.exception(
                "Admin notification write failed; continuing.")
            return []

    @classmethod
    def notify_for_audit(cls, audit_log, *, title=None, message=None, link='',
                         event_key=None, category=None, recipient=None,
                         metadata=None):
        """Notify from an existing audit record using the AUTO_NOTIFY spec."""
        cfg = AUTO_NOTIFY.get(getattr(audit_log, 'action', ''))
        if cfg is None:
            return []
        resolved_category = category or cfg['category']
        resolved_title = title or cfg['title']
        resolved_event_key = event_key or '{}:{}'.format(
            audit_log.action, audit_log.request_id or audit_log.id)
        description = getattr(audit_log, 'description', '') or ''
        message = message or description or resolved_title
        return cls.notify(
            resolved_category,
            resolved_title,
            message,
            link=link,
            event_key=resolved_event_key,
            event_type=audit_log.action,
            severity=cfg['severity'],
            audit_log=audit_log,
            metadata=metadata,
        )

    @staticmethod
    def _prepare(*, category, title, message, link, event_key, event_type,
                 severity, audit_log, recipient, actor, resource_type,
                 resource_id, request_id, metadata):
        if audit_log is not None:
            if not event_type:
                event_type = getattr(audit_log, 'action', '') or ''
            if not severity or severity == 'info':
                severity = getattr(audit_log, 'severity', '') or 'info'
            if actor is None:
                actor = getattr(audit_log, 'actor', None)
            if resource_type is None:
                resource_type = getattr(audit_log, 'object_type', '') or ''
            if resource_id is None:
                resource_id = getattr(audit_log, 'object_id', '') or ''
            if not request_id:
                request_id = getattr(audit_log, 'request_id', '') or ''
        if not request_id:
            request_id = AuditLogService.current_request_id() or ''
        if not resource_type:
            resource_type = ''
        if resource_id is None:
            resource_id = ''
        return {
            'category': category or 'system',
            'title': title or event_type or 'Notification',
            'message': message or '',
            'link': link or '',
            'event_key': event_key or '',
            'event_type': event_type or '',
            'severity': severity or 'info',
            'audit_log': audit_log,
            'recipient': recipient,
            'actor': actor,
            'resource_type': resource_type,
            'resource_id': str(resource_id) if resource_id else '',
            'request_id': request_id,
            'metadata': sanitize(metadata) if metadata else {},
        }


def _create_notifications(*, category, title, message, link, event_key,
                          event_type, severity, audit_log, recipient, actor,
                          resource_type, resource_id, request_id, metadata):
    """Create notification rows via the legacy helper (which owns the
    (recipient, event_key) dedupe loop)."""
    return notify_staff(
        category=category,
        title=title,
        message=message,
        link=link,
        event_key=event_key,
        recipient=recipient,
        event_type=event_type,
        severity=severity,
        audit_log=audit_log,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        metadata=metadata,
    )
