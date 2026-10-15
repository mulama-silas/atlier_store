import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import jwt
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from audit.models import AuditLog
from catalog.models import Category, Product, ProductVariant
from orders.models import Order
from payments.models import PaymentIntent

from .models import Receipt, ReceiptSequence
from .services import email_receipt, generate_receipt, next_receipt_number

_TEMP_MEDIA = tempfile.mkdtemp(prefix='modeza-receipts-')
TEST_SECRET = 'test-secret-that-is-at-least-32-bytes'


@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
            'OPTIONS': {'location': _TEMP_MEDIA},
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    },
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='receipts@modeza.test',
)
class ReceiptNumberTests(TestCase):
    def test_numbers_are_sequential_per_year(self):
        year = django_timezone.now().year
        first = next_receipt_number()
        second = next_receipt_number()
        self.assertEqual(first, f'RCP-{year}-000001')
        self.assertEqual(second, f'RCP-{year}-000002')
        self.assertEqual(ReceiptSequence.objects.filter(year=year).count(), 1)
        self.assertEqual(ReceiptSequence.objects.get(year=year).last_number, 2)

    def test_number_matches_expected_format(self):
        self.assertTrue(
            re.fullmatch(r'RCP-\d{4}-\d{6}', next_receipt_number()))


@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
            'OPTIONS': {'location': _TEMP_MEDIA},
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    },
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='receipts@modeza.test',
    SUPABASE_JWT_SECRET=TEST_SECRET,
    SUPABASE_JWT_ISSUER='',
    PAYMENT_WEBHOOK_SECRET='local-development-payment-secret',
    MPESA_CALLBACK_SECRET='local-development-mpesa-secret',
    # These tests exercise the *confirm* path — an intent that stays pending
    # until /api/payments/confirm or a Daraja callback settles it. The
    # sandbox gateway would complete the intent inside create_intent and turn
    # every confirm below into a no-op.
    PAYMENT_SANDBOX=False,
)
class ReceiptApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.category = Category.objects.create(name='Bags', slug='bags')
        self.product = Product.objects.create(
            category=self.category, name='Leather Bag', slug='leather-bag',
            description='A structured leather bag for daily use.',
            price_minor=30000, status=Product.Status.ACTIVE)
        self.variant = ProductVariant.objects.create(
            product=self.product, sku='BAG-ONE', stock_quantity=5)
        self.client.post('/api/cart/items', {'variantId': str(
            self.variant.id), 'quantity': 1}, format='json',
            HTTP_X_CART_ID='receipt-cart')
        created = self.client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace', 'email': 'ada@example.com',
            'phone': '0712345678', 'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='receipt-cart')
        self.order = Order.objects.get(
            order_number=created.json()['orderNumber'])
        self.headers = {'HTTP_X_CART_ID': 'receipt-cart'}

    def _create_intent(self):
        return self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers).json()

    def _confirm_payment(self, intent_id):
        return self.client.post(
            '/api/payments/webhook', {
                'event': 'payment_intent.succeeded',
                'data': {'paymentIntentId': intent_id,
                         'transactionId': 'TXN-ABCDE12345'},
            }, format='json',
            HTTP_X_WEBHOOK_SIGNATURE='local-development-payment-secret',
            HTTP_X_EVENT_ID=f'receipt-test-{uuid.uuid4().hex}')

    def test_provider_callback_generates_receipt(self):
        intent = self._create_intent()
        confirmed = self._confirm_payment(intent['id'])
        self.assertEqual(confirmed.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(receipt.status, Receipt.Status.GENERATED)
        self.assertTrue(re.match(r'RCP-\d{4}-\d{6}$', receipt.receipt_number))
        self.assertEqual(receipt.amount_minor, self.order.total_minor)
        self.assertEqual(receipt.currency, 'KES')
        self.assertEqual(receipt.gateway_reference, 'TXN-ABCDE12345')
        self.assertGreater(receipt.payload_size, 0)
        self.assertTrue(receipt.pdf_key.endswith(
            f'{receipt.receipt_number}.pdf'))
        self.assertEqual(receipt.snapshot['customer']['email'], 'ada@example.com')
        self.assertEqual(len(receipt.snapshot['items']), 1)
        self.assertEqual(receipt.snapshot['items'][0]['product_name'], 'Leather Bag')
        self.assertEqual(receipt.snapshot['total_minor'], self.order.total_minor)

    def test_repeated_confirmation_does_not_duplicate_receipt(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        self._confirm_payment(intent['id'])
        self.assertEqual(Receipt.objects.filter(order=self.order).count(), 1)

    def test_generate_receipt_is_idempotent(self):
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.save(update_fields=['payment_status'])
        first = generate_receipt(self.order)
        second = generate_receipt(self.order)
        self.assertEqual(first.receipt_number, second.receipt_number)
        self.assertEqual(Receipt.objects.filter(order=self.order).count(), 1)

    def test_mpesa_callback_generates_receipt(self):
        intent = self._create_intent()
        intent_obj = PaymentIntent.objects.get(id=intent['id'])
        intent_obj.client_secret = 'ws_CO_20260922'
        intent_obj.save(update_fields=['client_secret'])
        callback = {
            'Body': {'stkCallback': {
                'CheckoutRequestID': 'ws_CO_20260922',
                'ResultCode': 0,
                'CallbackMetadata': {'Item': [
                    {'Name': 'MpesaReceiptNumber', 'Value': 'TXN987654321'}],
                },
            }},
        }
        response = self.client.post(
            '/api/payments/mpesa/callback?token=local-development-mpesa-secret',
            callback, format='json')
        self.assertEqual(response.status_code, 200)
        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(receipt.status, Receipt.Status.GENERATED)
        self.assertEqual(receipt.gateway_reference, 'TXN987654321')
        self.assertEqual(receipt.checkout_request_id, 'ws_CO_20260922')

        duplicate = self.client.post(
            '/api/payments/mpesa/callback?token=local-development-mpesa-secret',
            callback, format='json')
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(Receipt.objects.filter(order=self.order).count(), 1)

    def test_receipt_metadata_endpoint(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['status'])
        receipt = Receipt.objects.get(order=self.order)

        response = self.client.get(
            f"/api/orders/{self.order.order_number}/receipt", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['receiptNumber'], receipt.receipt_number)
        self.assertEqual(data['orderNumber'], self.order.order_number)
        self.assertEqual(data['status'], 'generated')
        self.assertEqual(data['gatewayReference'], 'TXN-ABCDE12345')
        self.assertEqual(
            data['downloadPath'],
            f'/api/receipts/{receipt.receipt_number}/download')
        self.assertEqual(data['amount'], float(self.order.total_minor) / 100)

    def test_receipt_endpoint_forbidden_for_other_cart(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        response = self.client.get(
            f"/api/orders/{self.order.order_number}/receipt",
            HTTP_X_CART_ID='other-cart')
        self.assertEqual(response.status_code, 403)

    def test_receipt_metadata_withheld_until_admin_confirms(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        # Paid but still pending approval: metadata is withheld.
        response = self.client.get(
            f"/api/orders/{self.order.order_number}/receipt", **self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'RECEIPT_NOT_READY')

        # After admin confirmation the same receipt becomes visible.
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['status'])
        response = self.client.get(
            f"/api/orders/{self.order.order_number}/receipt", **self.headers)
        self.assertEqual(response.status_code, 200)

    def test_receipt_endpoint_missing_when_none_generated(self):
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['status'])
        response = self.client.get(
            f"/api/orders/{self.order.order_number}/receipt", **self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'RECEIPT_NOT_FOUND')

    def test_download_returns_pdf(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['status'])
        receipt = Receipt.objects.get(order=self.order)

        response = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(
            f'attachment; filename="{receipt.receipt_number}.pdf"',
            response['Content-Disposition'])
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_download_forbidden_for_other_cart(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        receipt = Receipt.objects.get(order=self.order)

        response = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download',
            HTTP_X_CART_ID='other-cart')
        self.assertEqual(response.status_code, 403)

    def test_download_withheld_until_admin_confirms(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        receipt = Receipt.objects.get(order=self.order)

        response = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download', **self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'RECEIPT_NOT_READY')

        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['status'])
        response = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download', **self.headers)
        self.assertEqual(response.status_code, 200)

    def test_authenticated_user_can_download_own_receipt(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(
            username='ada', password='x')
        self.order.user = user
        self.order.status = Order.Status.CONFIRMED
        self.order.save(update_fields=['user', 'status'])
        self.client.force_login(user)
        self._create_intent()
        intent = PaymentIntent.objects.get(order=self.order)
        self._confirm_payment(str(intent.id))
        self.order.refresh_from_db()
        receipt = Receipt.objects.get(order=self.order)

        self.client.logout()
        guest = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download',
            HTTP_X_CART_ID='receipt-cart')
        self.assertEqual(guest.status_code, 403)

        self.client.force_login(user)
        session = self.client.get(
            f'/api/receipts/{receipt.receipt_number}/download')
        self.assertEqual(session.status_code, 200)
        self.assertTrue(b''.join(
            session.streaming_content).startswith(b'%PDF'))

    def test_generation_failure_never_breaks_payment(self):
        intent = self._create_intent()
        with mock.patch('receipts.services.default_storage.save',
                        side_effect=OSError('disk full')):
            confirmed = self._confirm_payment(intent['id'])
        self.assertEqual(confirmed.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(receipt.status, Receipt.Status.FAILED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_admin_can_regenerate_failed_receipt(self):
        intent = self._create_intent()
        with mock.patch('receipts.services.default_storage.save',
                        side_effect=OSError('disk full')):
            self._confirm_payment(intent['id'])
        receipt = Receipt.objects.get(order=self.order)
        self.assertEqual(receipt.status, Receipt.Status.FAILED)

        self._auth_staff()
        response = self.client.post(
            f'/api/receipts/{receipt.receipt_number}/regenerate')
        self.assertEqual(response.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.GENERATED)
        self.assertTrue(receipt.pdf_key)
        self.assertGreater(receipt.payload_size, 0)
        self.assertEqual(
            response.json()['receiptNumber'], receipt.receipt_number)

    def test_customer_cannot_regenerate_receipt(self):
        intent = self._create_intent()
        self._confirm_payment(intent['id'])
        receipt = Receipt.objects.get(order=self.order)
        self._auth_staff('customer')
        response = self.client.post(
            f'/api/receipts/{receipt.receipt_number}/regenerate')
        self.assertEqual(response.status_code, 403)

    def test_receipt_email_withheld_until_admin_confirms(self):
        from orders.services import approve_order
        intent = self._create_intent()
        with self.captureOnCommitCallbacks(execute=True):
            self._confirm_payment(intent['id'])
        receipt = Receipt.objects.get(order=self.order)
        # Payment alone must not email the receipt while approval is pending.
        self.assertEqual(
            [m for m in mail.outbox if receipt.receipt_number in m.subject],
            [])
        self.order.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            approve_order(self.order)
        # Confirming the payment also queues its own payment email, so narrow
        # the assertion to the one message that carries this receipt.
        messages = [m for m in mail.outbox if receipt.receipt_number in m.subject]
        self.assertEqual(len(messages), 1)
        email = messages[0]
        self.assertEqual(email.to, ['ada@example.com'])
        self.assertEqual(len(email.attachments), 1)
        filename, payload, content_type = email.attachments[0]
        self.assertEqual(filename, f'{receipt.receipt_number}.pdf')
        self.assertEqual(content_type, 'application/pdf')
        self.assertTrue(payload.startswith(b'%PDF'))
        receipt.refresh_from_db()
        self.assertIsNotNone(receipt.email_sent_at)
        self.assertEqual(receipt.email_attempts, 1)

    def test_email_receipt_is_idempotent(self):
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.save(update_fields=['payment_status'])
        receipt = generate_receipt(self.order)
        email_receipt(receipt)
        email_receipt(receipt)
        self.assertEqual(len(mail.outbox), 1)
        receipt.refresh_from_db()
        self.assertEqual(receipt.email_attempts, 1)

    # -- helpers -----------------------------------------------------------

    def _auth_staff(self, role='staff'):
        now = datetime.now(timezone.utc)
        token = jwt.encode({
            'sub': f'{role}-user', 'email': f'{role}@example.com',
            'aud': 'authenticated', 'iat': now,
            'exp': now + timedelta(minutes=5),
            'app_metadata': {'role': role}},
            TEST_SECRET, algorithm='HS256')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')


@override_settings(
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
            'OPTIONS': {'location': _TEMP_MEDIA},
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    },
    SUPABASE_JWT_SECRET=TEST_SECRET,
    SUPABASE_JWT_ISSUER='',
    PAYMENT_WEBHOOK_SECRET='local-development-payment-secret',
    # Same reason as ReceiptApiTests: the assertions below are about what
    # /api/payments/confirm does, so the intent must still be pending there.
    PAYMENT_SANDBOX=False,
)
class ReceiptAuditTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.category = Category.objects.create(name='Bags', slug='bags')
        self.product = Product.objects.create(
            category=self.category, name='Leather Bag', slug='leather-bag',
            description='A structured leather bag for daily use.',
            price_minor=30000, status=Product.Status.ACTIVE)
        self.variant = ProductVariant.objects.create(
            product=self.product, sku='BAG-ONE', stock_quantity=5)
        self.client.post('/api/cart/items', {'variantId': str(
            self.variant.id), 'quantity': 1}, format='json',
            HTTP_X_CART_ID='audit-cart')
        created = self.client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace', 'email': 'ada@example.com',
            'phone': '0712345678', 'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='audit-cart')
        self.order = Order.objects.get(
            order_number=created.json()['orderNumber'])
        self.headers = {'HTTP_X_CART_ID': 'audit-cart'}

    def test_receipt_generated_is_audited(self):
        intent = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers).json()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                '/api/payments/webhook', {
                    'event': 'payment_intent.succeeded',
                    'data': {'paymentIntentId': intent['id'],
                             'transactionId': 'TXN-ABCDE12345'},
                }, format='json',
                HTTP_X_WEBHOOK_SIGNATURE='local-development-payment-secret',
                HTTP_X_EVENT_ID=f'receipt-audit-{uuid.uuid4().hex}')
        receipt = Receipt.objects.get(order=self.order)
        self.assertTrue(
            AuditLog.objects.filter(
                action='receipt_generated',
                object_id=str(receipt.pk)).exists()
            or AuditLog.objects.filter(
                action='receipt_generated',
                object_repr=receipt.receipt_number).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action='payment_success',
                object_id=str(self.order.pk)).exists())
