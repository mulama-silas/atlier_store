"""Lifecycle of an outbound email: queue, claim, deliver, classify, retry.

Rules the rest of the system depends on:

* ``queue_email`` never raises — a broken notification must not break an order.
* Dispatch always happens after the DB commit, so a worker can never read
  uncommitted state and a rolled-back order never produces an email.
* ``EmailLog`` (Postgres) owns retry state, not Celery. Render's free Redis is
  in-memory, so a restart can lose the queued *message*; the log is the source
  of truth ``requeue_stuck_emails`` re-derives work from.
"""

import logging
import random
import smtplib as smtp
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import BadHeaderError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from .constants import (
    ADMIN_EMAIL_TYPES,
    ALLOWED_EMAIL_TYPES,
    CUSTOMER_EMAIL_TYPES,
    EMAIL_RETRY_DELAYS,
    JITTER_RATIO,
    MAX_ATTEMPTS,
    MAX_BODY_CHARS,
)
from .models import EmailLog

logger = logging.getLogger('emails')

#: Structural/content problems: re-sending identical bytes cannot succeed.
PERMANENT_ERRORS = (
    BadHeaderError,
    ValidationError,
    ValueError,
    smtp.SMTPNotSupportedError,
    smtp.SMTPSenderRefused,
)


def _looks_like_email(value):
    return bool(value) and '@' in value and '.' in value.split('@')[-1]


def _default_recipient(email_type):
    """Admin alerts go to one operations inbox rather than fanning out to every
    staff account — the in-app ``notify_staff`` channel already fans out."""
    if email_type in ADMIN_EMAIL_TYPES:
        return getattr(settings, 'STORE_EMAIL', '') or ''
    return ''


def _default_key(email_type, *, related_order, related_payment,
                 related_import_job, related_user):
    """Deterministic key derived from the business object that caused the send.

    This is what makes a duplicated webhook/callback/re-entrant service call a
    no-op instead of a second email.
    """
    if related_order is not None:
        return f'{email_type}:order:{related_order.pk}'
    if related_payment is not None:
        return f'{email_type}:payment:{related_payment.pk}'
    if related_import_job is not None:
        return f'{email_type}:import:{related_import_job.pk}'
    if related_user is not None:
        return f'{email_type}:user:{related_user.pk}'
    return f'{email_type}:random:{uuid.uuid4().hex}'


def _clean_subject(subject):
    # A CR/LF in the subject makes django.core.mail raise BadHeaderError.
    return ' '.join(str(subject or '').split())[:255]


def classify_failure(exc):
    """``'temporary'`` (retry) or ``'permanent'`` (stop now).

    A transport may assert its own verdict with a boolean ``permanent``
    attribute — the HTTPS API backend does, because HTTP 401/403 mean "your
    key is wrong" and retrying for 40 minutes would only burn the attempts.
    An SMTP status code is authoritative next: 4xx is transient, 5xx is not.
    Failing that, known permanent exception types win; everything else is
    treated as transient because the ladder is bounded anyway.
    """
    seen = set()
    chain = []
    queue = [exc]
    while queue and len(chain) < 10:
        current = queue.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        queue.extend((current.__cause__, current.__context__))

    for node in chain:
        verdict = getattr(node, 'permanent', None)
        if isinstance(verdict, bool):
            return 'permanent' if verdict else 'temporary'
    for node in chain:
        code = getattr(node, 'smtp_code', None)
        if isinstance(code, int):
            return 'temporary' if 400 <= code < 500 else 'permanent'
    for node in chain:
        if isinstance(node, PERMANENT_ERRORS):
            return 'permanent'
    return 'temporary'


def _retry_delay(attempt_count):
    index = min(max(attempt_count - 1, 0), len(EMAIL_RETRY_DELAYS) - 1)
    base = EMAIL_RETRY_DELAYS[index]
    return base + random.randint(0, max(1, int(base * JITTER_RATIO)))


def _format_error(exc):
    code = getattr(exc, 'smtp_code', None)
    prefix = f'SMTP {code}: ' if isinstance(code, int) else ''
    return f'{prefix}{exc.__class__.__name__}: {exc}'[:1000]


def delivery_mode():
    """Resolve how a freshly queued message reaches its transport.

    ``EMAIL_DELIVERY_MODE`` wins when set. When it is not, the historical
    behaviour stands — a Celery worker if there is one, inline delivery
    otherwise — so an unconfigured deployment keeps working exactly as it
    did before the switch existed.
    """
    explicit = (getattr(settings, 'EMAIL_DELIVERY_MODE', '') or '').strip().lower()
    if explicit:
        return explicit
    return 'worker' if getattr(settings, 'CELERY_WORKER_ENABLED', False) else 'inline'


def email_enabled():
    """The subsystem's master switch.

    ``EMAIL_ENABLED=False`` deactivates delivery without removing any of it:
    rows are still queued and visible in the admin, but no dispatch path may
    open a transport, and nothing may be recorded as SENT for mail that was
    never attempted.
    """
    return bool(getattr(settings, 'EMAIL_ENABLED', False))


def _dispatch(pk, *, force_inline=False):
    """Hand the log to its transport. Never raises.

    ``force_inline`` marks an *explicit* action by a human or by the sweeper
    (the admin Resend button, ``requeue_email_log``): the caller wants the
    attempt, and its error, right now rather than on the next sweep.
    """
    if not email_enabled():
        logger.debug('email %s not dispatched: EMAIL_ENABLED is false', pk)
        return
    mode = 'inline' if force_inline else delivery_mode()
    if mode == 'worker':
        from .tasks import send_email_log
        send_email_log.delay(str(pk))
    elif mode == 'deferred':
        # Leave the row QUEUED for POST /api/admin/emails/sweep. No socket
        # is ever opened inside the request that queued the mail.
        logger.debug('email %s deferred to the sweeper', pk)
    else:
        deliver_email_log(pk)


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------
def queue_email(*, email_type, subject, body_text, recipient_email=None,
                recipient_name='', idempotency_key=None, related_user=None,
                related_order=None, related_payment=None,
                related_import_job=None, notification=None, attachments=None,
                context=None, metadata=None, defer=True):
    """Persist an outbound message and schedule its delivery.

    Returns the :class:`EmailLog` (existing row for a duplicate event) or
    ``None`` when the request was rejected. Never raises.
    """
    try:
        return _queue_email(
            email_type=email_type, subject=subject, body_text=body_text,
            recipient_email=recipient_email, recipient_name=recipient_name,
            idempotency_key=idempotency_key, related_user=related_user,
            related_order=related_order, related_payment=related_payment,
            related_import_job=related_import_job, notification=notification,
            attachments=attachments, context=context, metadata=metadata,
            defer=defer,
        )
    except Exception:  # noqa: BLE001 - sending mail must never break a request
        logger.exception('queue_email(%s) failed', email_type)
        return None


def _queue_email(*, email_type, subject, body_text, recipient_email,
                 recipient_name, idempotency_key, related_user, related_order,
                 related_payment, related_import_job, notification, attachments,
                 context, metadata, defer):
    if email_type not in ALLOWED_EMAIL_TYPES:
        logger.error('rejected unknown email type %r', email_type)
        return None

    to = (recipient_email or _default_recipient(email_type) or '').strip()
    if not _looks_like_email(to):
        logger.error('rejected %s email: invalid recipient %r', email_type, to)
        return None

    if notification is not None:
        if not notification.get('event_key'):
            logger.error('%s email supplied a notification without an event_key',
                         email_type)
            return None
        if email_type not in CUSTOMER_EMAIL_TYPES:
            logger.error('%s is not a customer email type; dropping its '
                         'notification payload', email_type)
            notification = None

    explicit = bool(idempotency_key)
    key = idempotency_key or _default_key(
        email_type, related_order=related_order, related_payment=related_payment,
        related_import_job=related_import_job, related_user=related_user)
    if not explicit and not any((related_order, related_payment,
                                 related_import_job, related_user)):
        logger.warning('%s email has no related object; idempotency key is '
                       'random and duplicates will not be suppressed', email_type)

    defaults = {
        'email_type': email_type,
        'recipient_email': to,
        'recipient_name': (recipient_name or '')[:150],
        'sender_email': getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '',
        'subject': _clean_subject(subject),
        'body_text': str(body_text or '')[:MAX_BODY_CHARS],
        'template_name': email_type,
        'context': context or {},
        'attachments': attachments or [],
        'metadata': {**(metadata or {})},
        'status': EmailLog.Status.QUEUED,
        'max_attempts': MAX_ATTEMPTS,
        'related_user': related_user,
        'related_order': related_order,
        'related_payment': related_payment,
        'related_import_job': related_import_job,
    }
    if notification:
        defaults['metadata']['notification'] = notification

    try:
        log, created = EmailLog.objects.get_or_create(
            idempotency_key=key, defaults=defaults)
    except IntegrityError:
        # Two identical events raced; the loser re-reads the winner's row.
        log, created = EmailLog.objects.get(idempotency_key=key), False

    if not created:
        logger.info('duplicate %s email suppressed (key=%s, status=%s)',
                    email_type, key, log.status)
        return log

    if defer and transaction.get_connection().in_atomic_block:
        transaction.on_commit(lambda pk=log.pk: _dispatch(pk))
    else:
        _dispatch(log.pk)
    return log


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def deliver_email_log(pk):
    """Claim, send and record exactly one delivery attempt. Never raises.

    Returns the refreshed :class:`EmailLog`, or ``None`` if it is gone.
    """
    log = EmailLog.objects.filter(pk=pk).first()
    if log is None:
        logger.warning('email log %s not found', pk)
        return None
    if log.status in EmailLog.TERMINAL_STATUSES:
        return log
    if not email_enabled():
        # Deactivated: leave the row (and its attempt count) untouched rather
        # than recording an attempt nobody made.
        logger.debug('email %s not delivered: EMAIL_ENABLED is false', pk)
        return log

    now = timezone.now()
    # Atomic claim: only one executor may move QUEUED/RETRYING -> SENDING, so a
    # duplicate Celery message, a worker crash redelivery and an admin retry can
    # never send the same log twice concurrently.
    claimed = EmailLog.objects.filter(
        pk=pk,
        status__in=(EmailLog.Status.QUEUED, EmailLog.Status.RETRYING),
    ).update(
        status=EmailLog.Status.SENDING,
        attempt_count=F('attempt_count') + 1,
        started_at=now,
        updated_at=now,
    )
    if not claimed:
        log.refresh_from_db()
        logger.info('email %s already claimed (status=%s)', pk, log.status)
        return log

    log.refresh_from_db()
    try:
        from .senders import build_message
        build_message(log).send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - classified below
        return _record_failure(log, exc)

    sent_at = timezone.now()
    EmailLog.objects.filter(pk=pk).update(
        status=EmailLog.Status.SENT,
        sent_at=sent_at,
        next_retry_at=None,
        last_error='',
        updated_at=sent_at,
    )
    log.refresh_from_db()
    _after_send(log)
    logger.info('email %s delivered to %s on attempt %s',
                log.pk, log.recipient_email, log.attempt_count)
    return log


def _record_failure(log, exc):
    from . import hooks

    now = timezone.now()
    error = _format_error(exc)
    permanent = classify_failure(exc) == 'permanent'
    exhausted = log.attempt_count >= log.max_attempts

    if permanent or exhausted:
        EmailLog.objects.filter(pk=log.pk).update(
            status=EmailLog.Status.FAILED,
            failed_at=now,
            next_retry_at=None,
            last_error=error,
            updated_at=now,
        )
        log.refresh_from_db()
        hooks.after_fail(log)
        logger.error('email %s failed permanently after %s attempt(s): %s',
                     log.pk, log.attempt_count, error)
        return log

    delay = _retry_delay(log.attempt_count)
    EmailLog.objects.filter(pk=log.pk).update(
        status=EmailLog.Status.RETRYING,
        next_retry_at=now + timedelta(seconds=delay),
        last_error=error,
        updated_at=now,
    )
    log.refresh_from_db()
    logger.warning('email %s attempt %s failed (%s); retrying in %ss',
                   log.pk, log.attempt_count, error, delay)
    return log


def _after_send(log):
    """Post-delivery hooks (customer in-app notification, receipt bookkeeping).

    Failures here must not turn a delivered email into a failed one.
    """
    try:
        from . import hooks
        hooks.after_send(log)
    except Exception:  # noqa: BLE001
        logger.exception('after_send hook failed for email %s', log.pk)


# ---------------------------------------------------------------------------
# Admin-triggered resend
# ---------------------------------------------------------------------------
def retry_email_log(log):
    """Reset a terminal failure so it gets a fresh delivery ladder.

    Returns ``(log, dispatched)``. Only a FAILED log is accepted — resending a
    message that already went out would duplicate it.
    """
    if not email_enabled():
        logger.info('email %s not retried: EMAIL_ENABLED is false', log.pk)
        return log, False
    now = timezone.now()
    updated = EmailLog.objects.filter(
        pk=log.pk, status=EmailLog.Status.FAILED,
    ).update(
        status=EmailLog.Status.QUEUED,
        attempt_count=0,
        next_retry_at=None,
        last_error='',
        failed_at=None,
        started_at=None,
        updated_at=now,
    )
    log.refresh_from_db()
    if not updated:
        logger.info('email %s is not retryable (status=%s)', log.pk, log.status)
        return log, False

    _dispatch(log.pk, force_inline=True)
    # Re-read so the caller sees the post-dispatch state rather than the
    # QUEUED row it was reset to a moment earlier.
    log.refresh_from_db()
    return log, True


def requeue_email_log(log):
    """Attempt delivery of a QUEUED/RETRYING log whose dispatch was lost.

    Serves three callers: the recovery command (Render's in-memory Redis can
    drop a queued message on restart, while ``EmailLog`` survives), the
    sweeper endpoint, and a backoff-aware retry. ``EmailLog`` is always the
    source of truth — the broker is not. Returns ``True`` when an attempt was
    made, ``False`` when the row is not due or not eligible.
    """
    if not email_enabled():
        return False
    if log.status == EmailLog.Status.QUEUED:
        pass
    elif log.status == EmailLog.Status.RETRYING:
        if log.next_retry_at and log.next_retry_at > timezone.now():
            return False
    else:
        return False

    # Always inline: this is the sweeper's primitive, and delivering there is
    # the whole point — it runs in its own process, outside any checkout.
    _dispatch(log.pk, force_inline=True)
    logger.info('requeued email %s (status=%s)', log.pk, log.status)
    return True


# ---------------------------------------------------------------------------
# Sweep — the out-of-band delivery loop for EMAIL_DELIVERY_MODE=deferred
# ---------------------------------------------------------------------------
#: Give up on this run after this many consecutive non-SENT outcomes. When the
#: API is down every row would otherwise burn ``EMAIL_TIMEOUT`` seconds each;
#: better to report honestly and let the next tick try again.
SWEEP_MAX_CONSECUTIVE_FAILURES = 3


def pending_for_sweep(*, older_than=45, limit=10):
    """Return the rows a sweep should attempt, oldest first.

    * ``QUEUED`` older than ``older_than`` seconds — young rows are held back
      so the sweeper never races the request that is still queuing them.
    * ``RETRYING`` regardless of age; :func:`requeue_email_log` re-checks
      ``next_retry_at`` per row, which is what preserves the documented
      30s/2m/10m/30m ladder even though this queryset is deliberately broad.
    """
    threshold = timezone.now() - timedelta(seconds=max(0, int(older_than)))
    return list(
        EmailLog.objects.filter(
            Q(status=EmailLog.Status.QUEUED, queued_at__lte=threshold)
            | Q(status=EmailLog.Status.RETRYING)
        ).order_by('queued_at')[:max(1, int(limit))]
    )


def sweep_pending_emails(*, older_than=45, limit=10):
    """Deliver every due message and report what happened.

    Shared by ``manage.py requeue_stuck_emails`` and the sweeper endpoint so
    the two can never drift apart on what "due" means. Never raises.
    """
    if not email_enabled():
        logger.info('email sweep skipped: EMAIL_ENABLED is false')
        return {'found': 0, 'requeued': 0, 'skipped': 0, 'failed': 0}

    pending = pending_for_sweep(older_than=older_than, limit=limit)

    dispatched = 0
    skipped = 0
    failed = 0
    consecutive_failures = 0

    for log in pending:
        if not requeue_email_log(log):
            skipped += 1
            continue
        log.refresh_from_db()
        if log.status == EmailLog.Status.SENT:
            dispatched += 1
            consecutive_failures = 0
        else:
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= SWEEP_MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    'sweep stopping after %s consecutive failures',
                    consecutive_failures,
                )
                break

    return {
        'found': len(pending),
        'requeued': dispatched,
        'skipped': skipped,
        'failed': failed,
    }
