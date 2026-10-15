"""Behaviour of the centralised mailer.

Five things must hold or the whole subsystem is worse than the code it
replaced:

1. ``queue_email`` never raises and a duplicated business event sends exactly
   one message.
2. Delivery records one attempt per try, retries transients and stops on
   permanents — and a terminal failure raises one staff alert, not one per
   attempt.
3. Admin re-sends are explicit, audited, and cannot duplicate a delivered
   message.
4. Delivery side effects (the customer's in-app notification, receipt
   bookkeeping) reuse the call site's own ``event_key`` so nothing appears
   twice in the notification centre.
5. The staff pages stay permission-gated.
6. Deferred delivery never blocks the request that queued the mail, and the
   sweeper — the only thing that moves a row out of ``QUEUED`` in that mode —
   is token-guarded and honest about what it did. The HTTPS transport reports
   its own retry verdict so a bad API key fails fast instead of burning the
   whole ladder.
7. ``EMAIL_ENABLED=false`` deactivates delivery without removing it: rows are
   still queued and auditable, nothing touches a transport, nothing reaches
   SENT, and the admin says so plainly instead of pretending.
"""

import base64
import smtplib as smtp
import uuid as uuid_lib
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access_control.models import Permission, StaffProfile
from admin_ui.models import AdminNotification, CustomerNotification, notify_customer
from audit.models import AuditLog
from orders.models import Order
from receipts.models import Receipt

from .backends import EmailAPIError, ResendEmailBackend
from .models import EmailLog
from .services import (
    classify_failure,
    deliver_email_log,
    delivery_mode,
    email_enabled,
    queue_email,
    requeue_email_log,
    retry_email_log,
    sweep_pending_emails,
)

CUSTOMER_EVENT = 'customer-welcome:{pk}'


def make_log(**overrides):
    defaults = {
        'idempotency_key': f'test:{uuid_lib.uuid4().hex}',
        'email_type': 'welcome',
        'recipient_email': 'ada@example.com',
        'recipient_name': 'Ada',
        'subject': 'Welcome to MODEZA',
        'body_text': 'Thanks for joining us.',
    }
    defaults.update(overrides)
    return EmailLog.objects.create(**defaults)


def transient_failure():
    return smtp.SMTPResponseException(451, b'try again later')


def permanent_failure():
    return smtp.SMTPAuthenticationError(535, b'authentication failed')


class QueueTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ada', email='ada@example.com', password='pw')

    def queue(self, **overrides):
        payload = {
            'email_type': 'welcome',
            'subject': 'Welcome to MODEZA',
            'body_text': 'Thanks for joining us.',
            'recipient_email': 'ada@example.com',
            'recipient_name': 'Ada',
            'related_user': self.user,
        }
        payload.update(overrides)
        with self.captureOnCommitCallbacks(execute=True):
            return queue_email(**payload)

    def test_queues_then_delivers_one_message_after_commit(self):
        log = self.queue()

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.attempt_count, 1)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Welcome to MODEZA')
        self.assertEqual(message.to, ['ada@example.com'])
        # The HTML wrapper is attached as an alternative, never as the body.
        self.assertEqual(message.alternatives[0][1], 'text/html')
        self.assertIn('Thanks for joining us.', message.body)

    def test_the_same_business_event_is_emailed_exactly_once(self):
        first = self.queue()
        second = self.queue()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(EmailLog.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_an_unknown_email_type_is_rejected(self):
        self.assertIsNone(self.queue(email_type='definitely_not_a_type'))
        self.assertEqual(EmailLog.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_unusable_recipient_is_rejected(self):
        self.assertIsNone(self.queue(recipient_email='not-an-address'))
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_a_notification_without_an_event_key_is_rejected(self):
        """Without a key the notification centre cannot de-duplicate, so the
        whole email is dropped rather than risking a visible duplicate."""
        self.assertIsNone(self.queue(notification={'category': 'account'}))
        self.assertEqual(EmailLog.objects.count(), 0)

    def test_admin_mail_defaults_to_the_operations_inbox(self):
        log = queue_email(
            email_type='admin_low_stock',
            subject='Low stock',
            body_text='Luna Silk Dress is down to 2.',
        )

        self.assertIsNotNone(log)
        self.assertEqual(log.recipient_email, settings.STORE_EMAIL)

    def test_a_non_customer_type_drops_its_notification_payload(self):
        log = queue_email(
            email_type='bulk_import_completed',
            subject='Import finished',
            body_text='42 rows imported.',
            notification={'category': 'system', 'title': 'x',
                          'message': 'y', 'event_key': 'k'},
        )

        self.assertIsNotNone(log)
        self.assertNotIn('notification', log.metadata)

    def test_queue_email_swallows_infrastructure_errors(self):
        with patch('emails.services.EmailLog') as model:
            model.objects.get_or_create.side_effect = RuntimeError('db down')
            log = self.queue()

        self.assertIsNone(log)

    def test_a_transient_failure_is_recorded_for_the_retry_ladder(self):
        with patch('django.core.mail.EmailMessage.send',
                   side_effect=transient_failure()):
            log = self.queue()

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.RETRYING)
        self.assertEqual(log.attempt_count, 1)
        self.assertIsNotNone(log.next_retry_at)
        self.assertIn('SMTP 451', log.last_error)


class DeliveryTests(TestCase):
    def setUp(self):
        self.ops = get_user_model().objects.create_user(
            username='ops', email='ops@example.com', password='pw',
            is_staff=True)

    def test_a_transient_error_schedules_an_exponential_retry(self):
        log = make_log()

        with patch('django.core.mail.EmailMessage.send',
                   side_effect=transient_failure()):
            result = deliver_email_log(log.pk)

        result.refresh_from_db()
        self.assertEqual(result.status, EmailLog.Status.RETRYING)
        self.assertEqual(result.attempt_count, 1)
        self.assertIsNotNone(result.next_retry_at)
        self.assertIn('SMTP 451', result.last_error)
        # A transient attempt must not page anyone yet.
        self.assertFalse(AdminNotification.objects.filter(
            event_key=f'email-failed:{log.pk}').exists())

    def test_a_permanent_error_fails_immediately_and_alerts_staff_once(self):
        log = make_log()

        with patch('django.core.mail.EmailMessage.send',
                   side_effect=permanent_failure()):
            deliver_email_log(log.pk)

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertIsNotNone(log.failed_at)
        self.assertEqual(log.next_retry_at, None)
        self.assertIn('SMTP 535', log.last_error)

        bells = AdminNotification.objects.filter(
            event_key=f'email-failed:{log.pk}')
        self.assertEqual(bells.count(), 1)
        self.assertEqual(bells.get().recipient_id, self.ops.pk)
        self.assertEqual(bells.get().link, '/admin/dashboard/emails/?status=failed')

    def test_a_temporary_error_still_stops_when_attempts_are_exhausted(self):
        log = make_log(max_attempts=1)

        with patch('django.core.mail.EmailMessage.send',
                   side_effect=transient_failure()):
            deliver_email_log(log.pk)

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertEqual(log.attempt_count, 1)

    def test_a_terminal_log_is_never_touched_again(self):
        log = make_log(status=EmailLog.Status.SENT, sent_at=timezone.now())

        with patch('django.core.mail.EmailMessage.send') as send:
            result = deliver_email_log(log.pk)

        send.assert_not_called()
        self.assertEqual(result.status, EmailLog.Status.SENT)

    def test_repeated_terminal_failures_produce_a_single_staff_alert(self):
        log = make_log()

        with patch('django.core.mail.EmailMessage.send',
                   side_effect=permanent_failure()):
            deliver_email_log(log.pk)
        # A duplicate broker message must not page twice.
        with patch('django.core.mail.EmailMessage.send',
                   side_effect=permanent_failure()):
            deliver_email_log(log.pk)

        self.assertEqual(
            AdminNotification.objects.filter(
                event_key=f'email-failed:{log.pk}').count(),
            1)


class RetryTests(TestCase):
    def test_only_a_failed_log_can_be_manually_retried(self):
        sent = make_log(status=EmailLog.Status.SENT, sent_at=timezone.now())

        log, dispatched = retry_email_log(sent)

        self.assertFalse(dispatched)
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_retry_resets_the_ladder_and_sends(self):
        log = make_log(
            status=EmailLog.Status.FAILED, attempt_count=5,
            failed_at=timezone.now(), last_error='SMTP 535: nope')

        log, dispatched = retry_email_log(log)

        self.assertTrue(dispatched)
        # ``retry_email_log`` returns as soon as the work is re-dispatched —
        # in production the worker owns the delivery from here on.
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.attempt_count, 1)
        self.assertEqual(log.last_error, '')
        self.assertEqual(len(mail.outbox), 1)

    def test_requeue_rebuilds_broker_work_from_the_database(self):
        queued = make_log()
        sent = make_log(status=EmailLog.Status.SENT, sent_at=timezone.now())
        due = make_log(
            status=EmailLog.Status.RETRYING,
            next_retry_at=timezone.now() - timedelta(seconds=1))
        waiting = make_log(
            status=EmailLog.Status.RETRYING,
            next_retry_at=timezone.now() + timedelta(hours=1))

        self.assertTrue(requeue_email_log(queued))
        self.assertTrue(requeue_email_log(due))
        self.assertFalse(requeue_email_log(sent))
        self.assertFalse(requeue_email_log(waiting))


class NotificationHookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ada', email='ada@example.com', password='pw')

    def log_with_notification(self, event_key, *, guest=False):
        return make_log(
            related_user=None if guest else self.user,
            metadata={'notification': {
                'category': 'account',
                'title': 'Welcome to MODEZA',
                'message': 'Your account is ready.',
                'link': '/account',
                'event_key': event_key,
                'event_type': 'welcome',
            }})

    def test_delivery_surfaces_the_message_in_app(self):
        key = CUSTOMER_EVENT.format(pk=self.user.pk)
        log = self.log_with_notification(key)

        deliver_email_log(log.pk)

        notification = CustomerNotification.objects.get(user=self.user)
        self.assertEqual(notification.event_key, key)
        self.assertEqual(notification.category, 'account')
        self.assertEqual(notification.title, 'Welcome to MODEZA')
        self.assertEqual(notification.link, '/account')

    def test_the_business_layer_can_pre_surface_the_same_event(self):
        key = CUSTOMER_EVENT.format(pk=self.user.pk)
        notify_customer(
            self.user, 'account', 'Welcome to MODEZA',
            'Your account is ready.', link='/account', event_key=key)
        log = self.log_with_notification(key)

        deliver_email_log(log.pk)

        self.assertEqual(
            CustomerNotification.objects.filter(user=self.user).count(), 1)

    def test_a_guest_gets_the_email_but_no_in_app_entry(self):
        key = CUSTOMER_EVENT.format(pk='guest')
        log = self.log_with_notification(key, guest=True)

        log = deliver_email_log(log.pk)

        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(CustomerNotification.objects.count(), 0)

    def test_no_notification_payload_means_no_bell(self):
        log = make_log(related_user=self.user)

        deliver_email_log(log.pk)

        self.assertEqual(CustomerNotification.objects.count(), 0)


class ReceiptHookTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            order_number='AT-RECEIPT-001',
            customer={'fullName': 'Ada'},
            subtotal_minor=1000, total_minor=1000)
        self.receipt = Receipt.objects.create(
            order=self.order, receipt_number='RCP-2026-000042')

    def test_successful_delivery_stamps_the_receipt(self):
        log = make_log(email_type='receipt',
                       metadata={'receipt_id': str(self.receipt.pk)})

        # Audit rows are correctly deferred to on_commit; the test transaction
        # never commits, so flush the callbacks to observe them.
        with self.captureOnCommitCallbacks(execute=True):
            deliver_email_log(log.pk)

        self.receipt.refresh_from_db()
        self.assertIsNotNone(self.receipt.email_sent_at)
        self.assertEqual(self.receipt.email_attempts, 1)
        self.assertEqual(self.receipt.email_error, '')
        self.assertTrue(AuditLog.objects.filter(
            action='receipt_email_sent',
            object_id=str(self.receipt.pk)).exists())

    def test_terminal_failure_records_the_error_on_the_receipt(self):
        log = make_log(email_type='receipt',
                       metadata={'receipt_id': str(self.receipt.pk)})

        with patch('django.core.mail.EmailMessage.send',
                   side_effect=permanent_failure()):
            with self.captureOnCommitCallbacks(execute=True):
                deliver_email_log(log.pk)

        self.receipt.refresh_from_db()
        self.assertIsNone(self.receipt.email_sent_at)
        self.assertEqual(self.receipt.email_attempts, 1)
        self.assertIn('SMTP 535', self.receipt.email_error)
        self.assertTrue(AuditLog.objects.filter(
            action='receipt_email_failed',
            object_id=str(self.receipt.pk)).exists())


class EmailAdminPageTests(TestCase):
    def setUp(self):
        self.ops = get_user_model().objects.create_user(
            username='ops', email='ops@example.com', password='pw',
            is_staff=True)
        self.enroll(self.ops)
        self.failed = make_log(
            email_type='bulk_import_failed',
            subject='Import failed', status=EmailLog.Status.FAILED,
            attempt_count=5, failed_at=timezone.now(),
            last_error='SMTP 535: authentication failed')
        self.sent = make_log(
            email_type='bulk_import_completed',
            subject='Import finished', status=EmailLog.Status.SENT,
            sent_at=timezone.now())
        self.client.force_login(self.ops)

    def enroll(self, user, codes=('emails.view', 'emails.manage')):
        profile, _ = StaffProfile.objects.get_or_create(user=user)
        profile.status = StaffProfile.Status.ACTIVE
        profile.direct_permissions.set(
            Permission.objects.filter(code__in=codes))
        profile.save(update_fields=['status'])
        return profile

    def test_list_page_shows_every_message(self):
        response = self.client.get(reverse('emails:admin-email-list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import failed')
        self.assertContains(response, 'Import finished')

    def test_status_filter_narrows_the_list(self):
        response = self.client.get(
            reverse('emails:admin-email-list'), {'status': 'FAILED'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import failed')
        self.assertNotContains(response, 'Import finished')

    def test_detail_page_renders_the_full_body(self):
        response = self.client.get(
            reverse('emails:admin-email-detail', args=[self.failed.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import failed')
        self.assertContains(response, 'SMTP 535')

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        self.client.logout()

        response = self.client.get(reverse('emails:admin-email-list'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_staff_without_the_permission_get_a_403(self):
        stranger = get_user_model().objects.create_user(
            username='stranger', email='stranger@example.com',
            password='pw', is_staff=True)
        self.enroll(stranger, codes=())
        self.client.force_login(stranger)

        response = self.client.get(reverse('emails:admin-email-list'))

        self.assertEqual(response.status_code, 403)

    def test_retry_puts_a_failed_message_back_on_the_wire(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                reverse('emails:admin-email-retry', args=[self.failed.pk]))

        self.assertEqual(response.status_code, 302)
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, EmailLog.Status.SENT)
        self.assertEqual(self.failed.attempt_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(AuditLog.objects.filter(
            action='email_retry_requested',
            object_id=str(self.failed.pk),
            result='success').exists())

    def test_a_delivered_message_cannot_be_sent_twice(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                reverse('emails:admin-email-retry', args=[self.sent.pk]))

        self.assertEqual(response.status_code, 302)
        self.sent.refresh_from_db()
        self.assertEqual(self.sent.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AuditLog.objects.filter(
            action='email_retry_requested',
            object_id=str(self.sent.pk),
            result='failure').exists())

    def test_bulk_retry_sends_only_what_is_sendable(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('emails:admin-email-bulk-retry'),
                {'ids': [str(self.failed.pk), str(self.sent.pk)]})

        self.assertEqual(response.status_code, 302)
        self.failed.refresh_from_db()
        self.sent.refresh_from_db()
        self.assertEqual(self.failed.status, EmailLog.Status.SENT)
        self.assertEqual(self.sent.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            AuditLog.objects.filter(
                action='email_retry_requested').count(),
            2)

    def test_bulk_retry_without_a_selection_is_rejected(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('emails:admin-email-bulk-retry'), {})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# EMAIL_DELIVERY_MODE=deferred — the request never opens a socket for mail
# ---------------------------------------------------------------------------
class DeferredDeliveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='deferred-ada', email='deferred.ada@example.com',
            password='pw')

    def queue(self):
        with self.captureOnCommitCallbacks(execute=True):
            return queue_email(
                email_type='welcome',
                subject='Welcome to MODEZA',
                body_text='Thanks for joining us.',
                recipient_email='ada@example.com',
                recipient_name='Ada',
                related_user=self.user,
            )

    @override_settings(EMAIL_DELIVERY_MODE='deferred')
    def test_a_deferred_message_is_queued_without_touching_the_transport(self):
        """The whole point of the mode: checkout returns before any network."""
        log = self.queue()

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(log.attempt_count, 0)
        self.assertIsNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_DELIVERY_MODE='deferred', CELERY_WORKER_ENABLED=True)
    def test_an_explicit_mode_wins_over_the_celery_switch(self):
        self.assertEqual(delivery_mode(), 'deferred')

    @override_settings(EMAIL_DELIVERY_MODE='', CELERY_WORKER_ENABLED=True)
    def test_an_unset_mode_follows_the_worker_switch(self):
        self.assertEqual(delivery_mode(), 'worker')

    @override_settings(EMAIL_DELIVERY_MODE='', CELERY_WORKER_ENABLED=False)
    def test_an_unset_mode_without_a_worker_stays_inline(self):
        self.assertEqual(delivery_mode(), 'inline')

    @override_settings(EMAIL_DELIVERY_MODE='deferred')
    def test_a_deferred_message_is_still_delivered_on_demand(self):
        """The admin Resend button is an explicit human action: it goes now."""
        log = self.queue()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)

        dispatched = requeue_email_log(log)

        self.assertTrue(dispatched)
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)


class SweepTests(TestCase):
    """``sweep_pending_emails`` is the shared primitive behind both
    ``manage.py requeue_stuck_emails`` and ``POST /api/admin/emails/sweep``.
    """

    def age(self, log, seconds):
        # queued_at is auto_now_add, so only a queryset can move it back.
        EmailLog.objects.filter(pk=log.pk).update(
            queued_at=timezone.now() - timedelta(seconds=seconds))

    @override_settings(EMAIL_DELIVERY_MODE='deferred')
    def test_a_queued_row_is_delivered_once_it_is_old_enough(self):
        log = make_log()
        self.age(log, 60)

        summary = sweep_pending_emails(older_than=45)

        self.assertEqual(
            summary, {'found': 1, 'requeued': 1, 'skipped': 0, 'failed': 0})
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.attempt_count, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_row_younger_than_the_threshold_is_left_alone(self):
        """So a sweep never races the request that is still writing the row."""
        log = make_log()
        self.age(log, 5)

        summary = sweep_pending_emails(older_than=45)

        self.assertEqual(
            summary, {'found': 0, 'requeued': 0, 'skipped': 0, 'failed': 0})
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_retrying_row_waits_for_its_backoff(self):
        """The 30s/2m/10m/30m ladder survives the broad RETRYING queryset
        because ``requeue_email_log`` re-checks ``next_retry_at`` per row."""
        log = make_log(
            status=EmailLog.Status.RETRYING,
            next_retry_at=timezone.now() + timedelta(seconds=300))

        summary = sweep_pending_emails()

        self.assertEqual(
            summary, {'found': 1, 'requeued': 0, 'skipped': 1, 'failed': 0})
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.RETRYING)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_due_retrying_row_is_delivered(self):
        log = make_log(
            status=EmailLog.Status.RETRYING,
            next_retry_at=timezone.now() - timedelta(seconds=1))

        summary = sweep_pending_emails()

        self.assertEqual(summary['found'], 1)
        self.assertEqual(summary['requeued'], 1)
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.SENT)

    def test_terminal_rows_are_not_part_of_a_sweep(self):
        make_log(status=EmailLog.Status.SENT, sent_at=timezone.now())
        make_log(status=EmailLog.Status.FAILED, failed_at=timezone.now())

        summary = sweep_pending_emails()

        self.assertEqual(summary['found'], 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_DELIVERY_MODE='deferred')
    def test_an_operator_resend_bypasses_the_deferral(self):
        log = make_log(status=EmailLog.Status.FAILED, failed_at=timezone.now())

        log, dispatched = retry_email_log(log)

        self.assertTrue(dispatched)
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_the_sweep_stops_after_three_consecutive_failures(self):
        """When the transport is down every row would burn EMAIL_TIMEOUT
        seconds; better to report honestly and let the next tick try."""
        for _ in range(4):
            self.age(make_log(), 60)

        with patch('emails.senders.build_message',
                   side_effect=Exception('transport exploded')):
            summary = sweep_pending_emails(older_than=45)

        self.assertEqual(
            summary, {'found': 4, 'requeued': 0, 'skipped': 0, 'failed': 3})
        # The fourth row was never touched.
        self.assertEqual(EmailLog.objects.filter(attempt_count=0).count(), 1)
        self.assertEqual(len(mail.outbox), 0)


class SweeperEndpointTests(TestCase):
    url = '/api/admin/emails/sweep'

    def setUp(self):
        # DRF throttles share one in-process cache across the whole run, so
        # start from a clean counter rather than whatever earlier tests spent.
        cache.clear()

    def age_due_rows(self, seconds=60):
        EmailLog.objects.filter(status=EmailLog.Status.QUEUED).update(
            queued_at=timezone.now() - timedelta(seconds=seconds))

    @override_settings(EMAIL_SWEEP_TOKEN='')
    def test_the_route_does_not_exist_until_a_token_is_configured(self):
        """An unconfigured deployment must not advertise a POST route that
        anyone on the internet can knock on."""
        response = self.client.post(self.url, HTTP_X_SWEEP_TOKEN='anything')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_SWEEP_TOKEN='sweep-secret')
    def test_a_wrong_token_is_rejected_and_audited(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url, HTTP_X_SWEEP_TOKEN='not-the-token')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AuditLog.objects.filter(
            action='security_event',
            result='failure',
            severity='critical').exists())

    @override_settings(EMAIL_SWEEP_TOKEN='sweep-secret')
    def test_a_missing_token_is_rejected(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 401)

    @override_settings(EMAIL_SWEEP_TOKEN='sweep-secret')
    def test_a_valid_token_delivers_every_due_message(self):
        make_log()
        self.age_due_rows()

        response = self.client.post(
            self.url, HTTP_X_SWEEP_TOKEN='sweep-secret')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'found': 1, 'requeued': 1, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailLog.objects.get().status,
                         EmailLog.Status.SENT)

    @override_settings(EMAIL_SWEEP_TOKEN='sweep-secret')
    def test_the_query_parameter_token_is_accepted_too(self):
        make_log()
        self.age_due_rows()

        response = self.client.post(f'{self.url}?token=sweep-secret')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)


# ---------------------------------------------------------------------------
# EMAIL_ENABLED=false — deactivated, not removed
# ---------------------------------------------------------------------------
class EmailKillSwitchTests(TestCase):
    """The subsystem must stay fully wired while delivering nothing.

    Deactivation is not removal: rows are still queued and auditable, but no
    dispatch path may touch a transport, and nothing may be recorded as SENT
    for mail nobody attempted.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='off-ada', email='off.ada@example.com', password='pw')

    def age_due_rows(self, seconds=60):
        EmailLog.objects.filter(status=EmailLog.Status.QUEUED).update(
            queued_at=timezone.now() - timedelta(seconds=seconds))

    def test_missing_email_setting_defaults_to_disabled(self):
        with patch('emails.services.settings', new=Mock(spec=[])):
            self.assertFalse(email_enabled())

    @override_settings(EMAIL_ENABLED=False)
    def test_queueing_still_records_the_message(self):
        with self.captureOnCommitCallbacks(execute=True):
            log = queue_email(
                email_type='welcome',
                subject='Welcome to MODEZA',
                body_text='Thanks for joining us.',
                recipient_email='ada@example.com',
                recipient_name='Ada',
                related_user=self.user,
            )

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(log.attempt_count, 0)
        self.assertIsNone(log.sent_at)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ENABLED=False)
    def test_delivery_never_claims_a_row(self):
        log = make_log()

        returned = deliver_email_log(log.pk)

        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(log.attempt_count, 0)
        self.assertEqual(returned.status, EmailLog.Status.QUEUED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ENABLED=False)
    def test_admin_resend_reports_refusal_instead_of_pretending(self):
        log = make_log(status=EmailLog.Status.FAILED, failed_at=timezone.now())

        returned, dispatched = retry_email_log(log)

        self.assertFalse(dispatched)
        returned.refresh_from_db()
        self.assertEqual(returned.status, EmailLog.Status.FAILED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ENABLED=False)
    def test_the_sweeper_primitive_refuses_to_dispatch(self):
        log = make_log()
        self.assertFalse(requeue_email_log(log))
        log.refresh_from_db()
        self.assertEqual(log.status, EmailLog.Status.QUEUED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ENABLED=False)
    def test_the_sweep_reports_no_work(self):
        for _ in range(3):
            make_log()
        self.age_due_rows()

        summary = sweep_pending_emails(older_than=45)

        self.assertEqual(
            summary, {'found': 0, 'requeued': 0, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            EmailLog.objects.filter(status=EmailLog.Status.SENT).count(), 0)

    @override_settings(EMAIL_ENABLED=False, EMAIL_SWEEP_TOKEN='sweep-secret')
    def test_the_sweeper_endpoint_reports_no_work_too(self):
        make_log()
        self.age_due_rows()

        response = self.client.post(
            '/api/admin/emails/sweep', HTTP_X_SWEEP_TOKEN='sweep-secret')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'found': 0, 'requeued': 0, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_ENABLED=False)
    def test_the_admin_list_page_explains_the_state(self):
        log = make_log()
        staff = get_user_model().objects.create_superuser(
            username='off-admin', password='pw', email='off.admin@example.com')
        self.client.force_login(staff)

        response = self.client.get(reverse('emails:admin-email-list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Email delivery is deactivated')
        # The row is still listed, and the re-send affordance is gone.
        self.assertContains(response, log.subject)
        self.assertNotContains(response, 'Re-send selected')

    @override_settings(EMAIL_ENABLED=False)
    def test_bulk_resend_says_so_instead_of_failing_silently(self):
        make_log()
        staff = get_user_model().objects.create_superuser(
            username='off-admin-2', password='pw',
            email='off.admin2@example.com')
        self.client.force_login(staff)

        response = self.client.post(
            reverse('emails:admin-email-bulk-retry'),
            {'ids': [str(EmailLog.objects.get().pk)]}, follow=True)

        self.assertContains(response, 'Email delivery is deactivated')
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# The HTTPS transport (Render's free plan blocks SMTP entirely)
# ---------------------------------------------------------------------------
class ResendBackendTests(TestCase):
    def message(self, *, html=False, attachment=False):
        # Deliberately a plain EmailMessage unless an HTML alternative is
        # asked for: the transport must not assume MultiAlternatives.
        cls = mail.EmailMultiAlternatives if html else mail.EmailMessage
        message = cls(
            'Receipt for AT-001', 'Thanks for your order.',
            'receipts@modeza.co.ke', ['ada@example.com'])
        message.extra_headers['Idempotency-Key'] = 'log-42'
        if html:
            message.attach_alternative('<p>Thanks</p>', 'text/html')
        if attachment:
            message.attach('receipt.pdf', b'%PDF-1.4 fake', 'application/pdf')
        return message

    @staticmethod
    def response(status_code=200, payload=None):
        reply = Mock()
        reply.status_code = status_code
        reply.json.return_value = (
            payload if payload is not None else {'id': 'email_1'})
        return reply

    @override_settings(RESEND_API_KEY='re_live_key', EMAIL_TIMEOUT=7)
    def test_the_message_is_posted_over_https_with_its_identity_headers(self):
        with patch('emails.backends.requests.post',
                   return_value=self.response()) as post:
            sent = ResendEmailBackend().send_messages([self.message()])

        self.assertEqual(sent, 1)
        self.assertEqual(post.call_args[0][0], 'https://api.resend.com/emails')
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs['timeout'], 7)
        self.assertEqual(kwargs['headers']['Authorization'],
                         'Bearer re_live_key')
        # Resend de-duplicates on this for 24h: a second safety net behind
        # the EmailLog idempotency key.
        self.assertEqual(kwargs['headers']['Idempotency-Key'], 'log-42')
        self.assertEqual(kwargs['json']['from'], 'receipts@modeza.co.ke')
        self.assertEqual(kwargs['json']['to'], ['ada@example.com'])
        self.assertEqual(kwargs['json']['subject'], 'Receipt for AT-001')
        self.assertEqual(kwargs['json']['text'], 'Thanks for your order.')

    @override_settings(RESEND_API_KEY='re_live_key')
    def test_the_html_part_and_the_attachment_travel_together(self):
        with patch('emails.backends.requests.post',
                   return_value=self.response()) as post:
            ResendEmailBackend().send_messages(
                [self.message(html=True, attachment=True)])

        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['html'], '<p>Thanks</p>')
        attachment = payload['attachments'][0]
        self.assertEqual(attachment['filename'], 'receipt.pdf')
        self.assertEqual(attachment['content_type'], 'application/pdf')
        self.assertEqual(
            attachment['content'],
            base64.b64encode(b'%PDF-1.4 fake').decode('ascii'))

    @override_settings(RESEND_API_KEY='re_live_key')
    def test_a_rejected_api_key_fails_permanently(self):
        """HTTP 401/403/400/422 mean the key or the sending domain is wrong;
        retrying for 40 minutes would only burn the ladder."""
        with patch('emails.backends.requests.post',
                   return_value=self.response(401, {'message': 'API key is invalid'})):
            with self.assertRaises(EmailAPIError) as caught:
                ResendEmailBackend().send_messages([self.message()])

        self.assertTrue(caught.exception.permanent)
        self.assertEqual(classify_failure(caught.exception), 'permanent')
        self.assertIn('HTTP 401', str(caught.exception))
        self.assertIn('API key is invalid', str(caught.exception))

    @override_settings(RESEND_API_KEY='re_live_key')
    def test_rate_limiting_is_only_temporary(self):
        with patch('emails.backends.requests.post',
                   return_value=self.response(429, {'message': 'Too many'})):
            with self.assertRaises(EmailAPIError) as caught:
                ResendEmailBackend().send_messages([self.message()])

        self.assertFalse(caught.exception.permanent)
        self.assertEqual(classify_failure(caught.exception), 'temporary')

    @override_settings(RESEND_API_KEY='re_live_key')
    def test_a_network_failure_is_only_temporary(self):
        with patch('emails.backends.requests.post',
                   side_effect=requests.exceptions.ConnectTimeout('timed out')):
            with self.assertRaises(EmailAPIError) as caught:
                ResendEmailBackend().send_messages([self.message()])

        self.assertFalse(caught.exception.permanent)
        self.assertEqual(classify_failure(caught.exception), 'temporary')

    @override_settings(RESEND_API_KEY='')
    def test_an_unconfigured_key_fails_fast_instead_of_hanging(self):
        with patch('emails.backends.requests.post') as post:
            with self.assertRaises(EmailAPIError) as caught:
                ResendEmailBackend().send_messages([self.message()])

        post.assert_not_called()
        self.assertTrue(caught.exception.permanent)
        self.assertEqual(classify_failure(caught.exception), 'permanent')
