from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductVariant
from orders.models import Order
from payments.daraja import DarajaError, normalize_ke_phone, initiate_stk_push
from payments.models import PaymentIntent
from receipts.models import Receipt


class DarajaPhoneTests(TestCase):
    def test_accepts_common_kenyan_phone_formats(self):
        self.assertEqual(normalize_ke_phone('0712 345 678'), '254712345678')
        self.assertEqual(normalize_ke_phone('+254 112 345 678'), '254112345678')
        self.assertEqual(normalize_ke_phone('712345678'), '254712345678')

    def test_rejects_invalid_phone_numbers(self):
        for phone in ('12345', '+1 202 555 0100', '254912345678'):
            with self.subTest(phone=phone), self.assertRaises(DarajaError):
                normalize_ke_phone(phone)

    @override_settings(MPESA_ENVIRONMENT='sandbox', MPESA_CONSUMER_KEY='key',
                       MPESA_CONSUMER_SECRET='secret', MPESA_SHORTCODE='174379',
                       MPESA_PASSKEY='passkey',
                       MPESA_CALLBACK_URL='https://example.test/api/payments/mpesa/callback')
    @patch('payments.daraja._request_json')
    def test_stk_amount_comes_from_minor_units(self, request):
        request.side_effect = [
            {'access_token': 'token'},
            {'ResponseCode': '0', 'MerchantRequestID': 'merchant-1',
             'CheckoutRequestID': 'checkout-1'},
        ]
        result = initiate_stk_push('0712345678', 34800, 'ORD-1', 'MODEZA ORD-1')
        self.assertEqual(result['CheckoutRequestID'], 'checkout-1')
        payload = request.call_args.kwargs['json']
        self.assertEqual(payload['Amount'], 348)
        self.assertEqual(payload['PhoneNumber'], '254712345678')
        self.assertEqual(payload['CallBackURL'], 'https://example.test/api/payments/mpesa/callback')

    @override_settings(MPESA_ENVIRONMENT='sandbox', MPESA_CONSUMER_KEY='key',
                       MPESA_CONSUMER_SECRET='secret', MPESA_SHORTCODE='174379',
                       MPESA_PASSKEY='passkey',
                       MPESA_CALLBACK_URL='https://example.test/callback')
    @patch('payments.daraja._request_json')
    def test_fractional_or_zero_kes_amount_is_rejected(self, request):
        for amount_minor in (0, 12550):
            with self.subTest(amount_minor=amount_minor), self.assertRaises(DarajaError):
                initiate_stk_push('0712345678', amount_minor, 'ORD-1', 'MODEZA ORD-1')
        request.assert_not_called()

    @override_settings(MPESA_ENVIRONMENT='sandbox', MPESA_CONSUMER_KEY='key',
                       MPESA_CONSUMER_SECRET='secret', MPESA_SHORTCODE='174379',
                       MPESA_PASSKEY='passkey',
                       MPESA_CALLBACK_URL='https://example.test/callback')
    @patch('payments.daraja.requests.request')
    def test_authentication_failure_is_sanitized(self, request):
        import requests
        request.return_value.raise_for_status.side_effect = requests.HTTPError('unauthorized')
        with self.assertRaises(DarajaError) as error:
            initiate_stk_push('0712345678', 1000, 'ORD-1', 'MODEZA ORD-1')
        self.assertEqual(error.exception.code, 'PROVIDER_UNAVAILABLE')
        self.assertNotIn('secret', str(error.exception))


class PaymentApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        category = Category.objects.create(name='Bags', slug='bags')
        product = Product.objects.create(category=category, name='Leather Bag', slug='leather-bag',
                                         description='A structured leather bag for daily use.', price_minor=30000, status=Product.Status.ACTIVE)
        variant = ProductVariant.objects.create(product=product, sku='BAG-ONE', stock_quantity=2)
        self.client.post('/api/cart/items', {'variantId': str(variant.id), 'quantity': 1},
                         format='json', HTTP_X_CART_ID='payment-cart')
        self.client.post('/api/orders', {'customer': {'fullName': 'Ada Lovelace', 'email': 'ada@example.com',
                         'phone': '0712345678', 'addressLine1': '1 Market Street',
                         'city': 'Nairobi', 'county': 'Nairobi'}},
                         format='json', HTTP_X_CART_ID='payment-cart')
        self.order = Order.objects.get(cart__cart_key='payment-cart')
        self.headers = {'HTTP_X_CART_ID': 'payment-cart'}

    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_stk_request_uses_server_total_and_stays_pending(self, push):
        response = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa',
            'phoneNumber': '+254712345678', 'amount': 1,
        }, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['amount'], 348)
        self.assertEqual(response.json()['status'], PaymentIntent.Status.PENDING)
        self.assertNotIn('clientSecret', response.json())
        self.assertNotIn('checkoutRequestId', response.json())
        push.assert_called_once_with('254712345678', self.order.total_minor,
                                     self.order.order_number, f'MODEZA {self.order.order_number}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_repeated_pending_request_reuses_same_provider_attempt(self, push):
        payload = {'orderNumber': self.order.order_number, 'method': 'mpesa'}
        first = self.client.post('/api/payments/create-intent', payload, format='json', **self.headers)
        second = self.client.post('/api/payments/create-intent', payload, format='json', **self.headers)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(PaymentIntent.objects.filter(order=self.order).count(), 1)
        push.assert_called_once()

    @override_settings(MPESA_CONSUMER_KEY='', MPESA_CONSUMER_SECRET='', MPESA_SHORTCODE='',
                       MPESA_PASSKEY='', MPESA_CALLBACK_URL='')
    def test_missing_configuration_fails_closed(self):
        response = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PaymentIntent.objects.get().status, PaymentIntent.Status.FAILED)

    def test_invalid_phone_does_not_create_payment_or_call_provider(self):
        response = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa',
            'phoneNumber': '12345'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentIntent.objects.exists())

    @patch('payments.services.initiate_stk_push', side_effect=DarajaError('STK_REJECTED', 'M-Pesa could not start the payment request. Please retry.'))
    def test_provider_rejection_fails_attempt_without_settling_order(self, push):
        response = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PaymentIntent.objects.get().status, PaymentIntent.Status.FAILED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    def test_malformed_callback_does_not_change_payment(self):
        response = self.client.post('/api/payments/mpesa/callback', {'Body': []}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentIntent.objects.exists())

    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_customer_confirmation_cannot_settle_pending_payment(self, push):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        response = self.client.post('/api/payments/confirm', {
            'orderNumber': self.order.order_number, 'paymentIntentId': created.json()['id'],
            'gatewayReference': 'CUSTOMER-SAYS-PAID'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    @patch('payments.views.query_stk_status', return_value={
        'ResponseCode': '0', 'ResultCode': '0', 'CheckoutRequestID': 'checkout-123'})
    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_verified_callback_is_idempotent_and_settles_order(self, push, query):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        callback = {'Body': {'stkCallback': {
            'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123',
            'ResultCode': 0, 'CallbackMetadata': {'Item': [
                {'Name': 'Amount', 'Value': 348},
                {'Name': 'MpesaReceiptNumber', 'Value': 'TXN987654321'}]},
        }}}
        first = self.client.post('/api/payments/mpesa/callback', callback, format='json')
        duplicate = self.client.post('/api/payments/mpesa/callback', callback, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(query.call_count, 1)
        intent = PaymentIntent.objects.get(id=created.json()['id'])
        self.assertEqual(intent.status, PaymentIntent.Status.SUCCEEDED)
        self.assertEqual(intent.gateway_reference, 'TXN987654321')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(Receipt.objects.filter(order=self.order).count(), 1)

    @patch('payments.views.query_stk_status', return_value={
        'ResponseCode': '0', 'ResultCode': '1032', 'CheckoutRequestID': 'checkout-123'})
    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_verified_cancellation_does_not_mark_order_paid(self, push, query):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        callback = {'Body': {'stkCallback': {
            'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123',
            'ResultCode': 1032, 'ResultDesc': 'Request cancelled by user'}}}
        self.client.post('/api/payments/mpesa/callback', callback, format='json')
        intent = PaymentIntent.objects.get(id=created.json()['id'])
        self.assertEqual(intent.status, PaymentIntent.Status.FAILED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_callback_amount_mismatch_does_not_settle_payment(self, push):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        callback = {'Body': {'stkCallback': {
            'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123',
            'ResultCode': 0, 'CallbackMetadata': {'Item': [
                {'Name': 'Amount', 'Value': 1},
                {'Name': 'MpesaReceiptNumber', 'Value': 'TXN987654321'}]},
        }}}
        response = self.client.post('/api/payments/mpesa/callback', callback, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaymentIntent.objects.get(id=created.json()['id']).status,
                         PaymentIntent.Status.PENDING)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    @patch('payments.views.query_stk_status', side_effect=TimeoutError('provider timed out'))
    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_delayed_provider_verification_keeps_order_pending(self, push, query):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        callback = {'Body': {'stkCallback': {
            'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123',
            'ResultCode': 0, 'CallbackMetadata': {'Item': [
                {'Name': 'Amount', 'Value': 348},
                {'Name': 'MpesaReceiptNumber', 'Value': 'TXN987654321'}]},
        }}}
        self.client.post('/api/payments/mpesa/callback', callback, format='json')
        self.assertEqual(PaymentIntent.objects.get(id=created.json()['id']).status,
                         PaymentIntent.Status.PENDING)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    def test_payment_intent_cannot_be_accessed_from_another_cart(self):
        response = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number}, format='json', HTTP_X_CART_ID='other-cart')
        self.assertEqual(response.status_code, 403)

    @patch('payments.services.initiate_stk_push', return_value={
        'MerchantRequestID': 'merchant-123', 'CheckoutRequestID': 'checkout-123'})
    def test_payment_status_is_bound_to_order_ownership(self, push):
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa'},
            format='json', **self.headers)
        response = self.client.get('/api/payments/status', {
            'orderNumber': self.order.order_number,
            'paymentIntentId': created.json()['id'],
        }, HTTP_X_CART_ID='other-cart')
        self.assertEqual(response.status_code, 403)
