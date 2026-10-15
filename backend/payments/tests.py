from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductVariant
from orders.models import Order
from payments.models import PaymentIntent
from receipts.models import Receipt


class PaymentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        category = Category.objects.create(name='Bags', slug='bags')
        product = Product.objects.create(category=category, name='Leather Bag', slug='leather-bag',
                                         description='A structured leather bag for daily use.', price_minor=30000, status=Product.Status.ACTIVE)
        variant = ProductVariant.objects.create(
            product=product, sku='BAG-ONE', stock_quantity=2)
        self.client.post('/api/cart/items', {'variantId': str(
            variant.id), 'quantity': 1}, format='json', HTTP_X_CART_ID='payment-cart')
        self.client.post('/api/orders', {'customer': {'fullName': 'Ada Lovelace', 'email': 'ada@example.com', 'phone': '0712345678',
                         'addressLine1': '1 Market Street', 'city': 'Nairobi', 'county': 'Nairobi'}}, format='json', HTTP_X_CART_ID='payment-cart')
        self.order = Order.objects.get(cart__cart_key='payment-cart')

    def test_create_and_confirm_payment_is_idempotent(self):
        headers = {'HTTP_X_CART_ID': 'payment-cart'}
        created = self.client.post('/api/payments/create-intent', {
                                   'orderNumber': self.order.order_number, 'method': 'mpesa'}, format='json', **headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['amount'], 348)
        intent_id = created.json()['id']

        confirmed = self.client.post('/api/payments/confirm', {
                                     'orderNumber': self.order.order_number, 'paymentIntentId': intent_id}, format='json', **headers)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()['paymentStatus'], 'paid')
        self.assertEqual(confirmed.json()['status'], 'pending')
        repeated = self.client.post('/api/payments/confirm', {
                                    'orderNumber': self.order.order_number, 'paymentIntentId': intent_id}, format='json', **headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(PaymentIntent.objects.get(
            id=intent_id).status, PaymentIntent.Status.SUCCEEDED)

    @override_settings(PAYMENT_SANDBOX=False)
    def test_customer_confirmation_cannot_settle_pending_intent(self):
        headers = {'HTTP_X_CART_ID': 'payment-cart'}
        created = self.client.post('/api/payments/create-intent', {
            'orderNumber': self.order.order_number, 'method': 'mpesa',
        }, format='json', **headers)
        intent_id = created.json()['id']

        confirmed = self.client.post('/api/payments/confirm', {
            'orderNumber': self.order.order_number,
            'paymentIntentId': intent_id,
            'gatewayReference': 'CUSTOMER-SAYS-PAID',
        }, format='json', **headers)

        self.assertEqual(confirmed.status_code, 400)
        self.assertIn('pending provider confirmation',
                      str(confirmed.json()))
        self.assertEqual(PaymentIntent.objects.get(
            id=intent_id).status, PaymentIntent.Status.PENDING)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status,
                         Order.PaymentStatus.PENDING)

    def test_payment_intent_cannot_be_accessed_from_another_cart(self):
        response = self.client.post('/api/payments/create-intent', {
                                    'orderNumber': self.order.order_number}, format='json', HTTP_X_CART_ID='other-cart')
        self.assertEqual(response.status_code, 403)

    def test_the_mock_gateway_completes_the_intent_so_the_order_can_be_approved(self):
        """Nothing in this backend issues a Daraja STK push, so the sandbox
        settles the intent inside create_intent. Without that the order never
        reaches PAID and the admin Approve button — gated on PAID — never
        appears, which is exactly the state production was stuck in."""
        headers = {'HTTP_X_CART_ID': 'payment-cart'}
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post('/api/payments/create-intent', {
                                       'orderNumber': self.order.order_number, 'method': 'mpesa'}, format='json', **headers)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['status'],
                         PaymentIntent.Status.SUCCEEDED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status,
                         Order.PaymentStatus.PAID)
        self.assertTrue(Receipt.objects.filter(order=self.order).exists())
        subjects = [message.subject for message in mail.outbox]
        self.assertEqual(
            subjects.count(
                f'Payment received for order {self.order.order_number}'),
            1)

    @override_settings(PAYMENT_SANDBOX=False)
    def test_disabling_the_mock_gateway_leaves_the_intent_pending(self):
        """The day a real STK push exists, PAYMENT_SANDBOX=false hands control
        back to the gateway instead of inventing a success."""
        headers = {'HTTP_X_CART_ID': 'payment-cart'}
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post('/api/payments/create-intent', {
                                       'orderNumber': self.order.order_number, 'method': 'mpesa'}, format='json', **headers)

        self.assertEqual(created.json()['status'], PaymentIntent.Status.PENDING)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status,
                         Order.PaymentStatus.PENDING)
        self.assertFalse(Receipt.objects.filter(order=self.order).exists())
        self.assertNotIn(
            f'Payment received for order {self.order.order_number}',
            [message.subject for message in mail.outbox])
