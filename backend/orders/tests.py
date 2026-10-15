import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from cart.models import Cart
from catalog.models import Category, Product, ProductVariant
from inventory.models import InventoryTransaction, StockReservation
from orders.models import Order
from orders.services import shipping_cost_minor, tax_cost_minor
from audit.models import AuditLog
from admin_ui.models import AdminNotification


class OrderApiTests(TestCase):
    def test_guest_cart_key_cannot_read_account_order(self):
        user_model = get_user_model()
        owner = user_model.objects.create_user(username='order-owner')
        cart = Cart.objects.create(cart_key=f'u:{owner.pk}', user=owner)
        order = Order.objects.create(
            order_number='AT-ACCOUNT-PRIVATE-001', cart=cart, user=owner,
            customer={'fullName': 'Private Buyer',
                      'email': 'private@example.com', 'phone': '0712345678'},
            subtotal_minor=1000, total_minor=1000,
            payment_method='mpesa')
        client = APIClient()

        listed = client.get('/api/orders', HTTP_X_CART_ID=cart.cart_key)
        detail = client.get(f'/api/orders/{order.order_number}',
                            HTTP_X_CART_ID=cart.cart_key)

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()['count'], 0)
        self.assertEqual(detail.status_code, 403)

        client.force_authenticate(user=owner)
        owned = client.get(f'/api/orders/{order.order_number}',
                           HTTP_X_CART_ID=cart.cart_key)
        self.assertEqual(owned.status_code, 200)

    def test_checkout_rejects_variant_deactivated_after_add_to_cart(self):
        from rest_framework.exceptions import ValidationError

        client = APIClient()
        category = Category.objects.create(name='Bags', slug='bags')
        product = Product.objects.create(
            category=category, name='Leather Bag', slug='leather-bag',
            description='A structured leather bag for daily use.',
            price_minor=30000, status=Product.Status.ACTIVE)
        variant = ProductVariant.objects.create(
            product=product, sku='BAG-ONE', stock_quantity=5)
        client.post('/api/cart/items', {'variantId': str(variant.id),
                     'quantity': 1}, format='json',
                    HTTP_X_CART_ID='deactivated-checkout-cart')
        variant.is_active = False
        variant.save(update_fields=['is_active'])

        created = client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace', 'email': 'ada@example.com',
            'phone': '0712345678', 'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='deactivated-checkout-cart')

        self.assertEqual(created.status_code, 400)
        self.assertFalse(Order.objects.filter(
            cart__cart_key='deactivated-checkout-cart').exists())
        self.assertEqual(Cart.objects.get(
            cart_key='deactivated-checkout-cart').items.count(), 1)

    def test_order_creation_validates_customer_fields(self):
        client = APIClient()
        category = Category.objects.create(name='Bags', slug='bags')
        product = Product.objects.create(
            category=category, name='Leather Bag', slug='leather-bag',
            description='A structured leather bag for daily use.',
            price_minor=30000, status=Product.Status.ACTIVE)
        variant = ProductVariant.objects.create(
            product=product, sku='BAG-VAL', stock_quantity=5)
        client.post('/api/cart/items', {'variantId': str(variant.id),
                     'quantity': 1}, format='json',
                    HTTP_X_CART_ID='validation-test-cart')

        # Missing required field: email
        created = client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace',
            'phone': '0712345678',
            'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='validation-test-cart')
        self.assertEqual(created.status_code, 400)
        self.assertIn('customer', created.json()['error']['details'])

        # Invalid email format
        created = client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace',
            'email': 'not-an-email',
            'phone': '0712345678',
            'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='validation-test-cart')
        self.assertEqual(created.status_code, 400)
        self.assertIn('customer', created.json()['error']['details'])

        # Phone too short
        created = client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace',
            'email': 'ada@example.com',
            'phone': '123',
            'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='validation-test-cart')
        self.assertEqual(created.status_code, 400)
        self.assertIn('customer', created.json()['error']['details'])

        # Valid data should succeed
        created = client.post('/api/orders', {'customer': {
            'fullName': 'Ada Lovelace',
            'email': 'ada@example.com',
            'phone': '0712345678',
            'addressLine1': '1 Market Street',
            'city': 'Nairobi', 'county': 'Nairobi'}},
            format='json', HTTP_X_CART_ID='validation-test-cart')
        self.assertEqual(created.status_code, 201)

    def test_reserve_variant_refuses_to_oversell_stock(self):
        from inventory.services import reserve_variant
        from rest_framework.exceptions import ValidationError

        category = Category.objects.create(name='Bags', slug='bags')
        product = Product.objects.create(
            category=category, name='Leather Bag', slug='leather-bag',
            description='A structured leather bag for daily use.',
            price_minor=30000, status=Product.Status.ACTIVE)
        variant = ProductVariant.objects.create(
            product=product, sku='BAG-OVERS', stock_quantity=3)
        cart = Cart.objects.create(cart_key='oversell-cart')
        order = Order.objects.create(
            order_number='AT-OVERSELL-001', cart=cart,
            customer={'fullName': 'Oversell Buyer'},
            subtotal_minor=30000, total_minor=30000,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING)

        for _ in range(3):
            reserve_variant(order, variant, 1)

        with self.assertRaises(ValidationError):
            reserve_variant(order, variant, 1)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 0)
        self.assertEqual(StockReservation.objects.filter(
            order=order, status=StockReservation.Status.ACTIVE).count(), 3)

    def test_shipping_cost_uses_20_percent_of_subtotal(self):
        self.assertEqual(shipping_cost_minor(10000, 'standard'), 2000)

    def test_shipping_cost_is_free_at_threshold(self):
        self.assertEqual(shipping_cost_minor(15000, 'standard'), 0)
        self.assertEqual(shipping_cost_minor(250000, 'standard'), 0)

    def test_express_shipping_is_flat_premium(self):
        self.assertEqual(shipping_cost_minor(1000, 'express'), 1500)
        self.assertEqual(shipping_cost_minor(50000, 'express'), 1500)

    def test_tax_cost_uses_16_percent_standard_rate(self):
        self.assertEqual(tax_cost_minor(25000), 4000)
        self.assertEqual(tax_cost_minor(0), 0)

    def test_customer_can_cancel_confirmed_order_through_order_api(self):
        response = self.client.post(
            '/api/orders',
            self.order_payload(),
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(response.status_code, 201)
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        order.status = Order.Status.CONFIRMED
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

        cancelled = self.client.post(
            f'/api/orders/{order_number}/cancel',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )

        self.assertEqual(cancelled.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUNDED)

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        get_user_model().objects.create_user(
            username=f'staff-{unique}', email=f'staff-{unique}@modeza.com',
            password='secret-pass-123', is_staff=True)
        category = Category.objects.create(
            name='Shoes', slug=f'shoes-{unique}')
        product = Product.objects.create(
            category=category,
            name='Leather Loafers',
            slug=f'leather-loafers-{unique}',
            description='Hand-finished leather loafers for everyday wear.',
            price_minor=25000,
            images=['/media/products/test-loafers.jpg'],
            status=Product.Status.ACTIVE,
        )
        self.variant = ProductVariant.objects.create(
            product=product, sku='LOAFER-40', size='40', stock_quantity=2)
        self.client.post('/api/cart/items', {'variantId': str(
            self.variant.id), 'quantity': 1}, format='json', HTTP_X_CART_ID='order-cart')

    def test_create_order_returns_absolute_order_item_image_url(self):
        response = self.client.post(
            '/api/orders',
            self.order_payload(),
            format='json',
            HTTP_X_CART_ID='order-cart',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['items'][0]['imageUrl'],
            'http://testserver/media/products/test-loafers.jpg',
        )

    def order_payload(self):
        return {'customer': {'fullName': 'Ada Lovelace', 'email': 'ada@example.com', 'phone': '0712345678', 'addressLine1': '1 Market Street', 'city': 'Nairobi', 'county': 'Nairobi'}, 'shippingMethod': 'standard', 'paymentMethod': 'mpesa'}

    def test_create_order_reserves_stock_and_snapshots_item(self):
        response = self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['subtotal'], 250)
        self.assertEqual(response.json()['items']
                         [0]['productName'], 'Leather Loafers')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 1)
        self.assertEqual(StockReservation.objects.count(), 1)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_create_order_free_shipping_and_vat_at_threshold(self):
        response = self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')

        self.assertEqual(response.status_code, 201)
        order = response.json()
        self.assertEqual(order['subtotal'], 250)
        self.assertEqual(order['shippingCost'], 0)
        self.assertEqual(order['tax'], 40)
        self.assertEqual(order['total'], 290)

    def test_customer_can_mark_delivered_order_as_received_through_order_api(self):
        response = self.client.post(
            '/api/orders',
            self.order_payload(),
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(response.status_code, 201)
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        order.status = Order.Status.DELIVERED
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

        received = self.client.post(
            f'/api/orders/{order_number}/receive',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )

        self.assertEqual(received.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.RECEIVED)

    def test_customer_can_request_refund_for_received_order(self):
        response = self.client.post(
            '/api/orders',
            self.order_payload(),
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(response.status_code, 201)
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        order.status = Order.Status.RECEIVED
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

        with self.captureOnCommitCallbacks(execute=True):
            returned = self.client.post(
                f'/api/orders/{order_number}/return',
                {'reason': 'Wrong size'},
                format='json',
                HTTP_X_CART_ID='order-cart',
            )

        self.assertEqual(returned.status_code, 200)
        order.refresh_from_db()
        audit = AuditLog.objects.filter(
            action='refund_requested',
            object_type='order',
            object_id=str(order.pk),
        )
        self.assertTrue(audit.exists())
        admins = AdminNotification.objects.filter(event_type='refund_requested')
        self.assertTrue(admins.exists())

    def test_refund_request_rejects_non_received_order(self):
        response = self.client.post(
            '/api/orders',
            self.order_payload(),
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        order_number = response.json()['orderNumber']

        returned = self.client.post(
            f'/api/orders/{order_number}/return',
            {'reason': ''},
            format='json',
            HTTP_X_CART_ID='order-cart',
        )

        self.assertEqual(returned.status_code, 400)

    def test_cancel_order_releases_stock_once(self):
        response = self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')
        order_number = response.json()['orderNumber']

        cancelled = self.client.post(
            f'/api/orders/{order_number}/cancel', HTTP_X_CART_ID='order-cart')
        self.assertEqual(cancelled.status_code, 200)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 2)
        self.assertEqual(StockReservation.objects.get().status,
                         StockReservation.Status.RELEASED)

        self.client.post(
            f'/api/orders/{order_number}/cancel', HTTP_X_CART_ID='order-cart')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 2)

    def test_mark_received_paid_settles_delivery_payment_order(self):
        payload = self.order_payload()
        payload['paymentMethod'] = 'cash_on_delivery'
        response = self.client.post(
            '/api/orders', payload, format='json', HTTP_X_CART_ID='order-cart')
        self.assertEqual(response.status_code, 201)
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status', 'updated_at'])
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)

        settled = self.client.post(
            f'/api/orders/{order_number}/mark-received-paid',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(settled.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.RECEIVED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_mark_received_paid_keeps_prepaid_order_paid(self):
        response = self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        order.status = Order.Status.DELIVERED
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=['status', 'payment_status', 'updated_at'])

        settled = self.client.post(
            f'/api/orders/{order_number}/mark-received-paid',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(settled.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.RECEIVED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_mark_received_paid_rejects_undelivered_order(self):
        response = self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')
        order_number = response.json()['orderNumber']

        settled = self.client.post(
            f'/api/orders/{order_number}/mark-received-paid',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(settled.status_code, 400)

    def test_mark_received_paid_settles_pending_delivery_payment_order(self):
        payload = self.order_payload()
        payload['paymentMethod'] = 'pay_on_delivery'
        response = self.client.post(
            '/api/orders', payload, format='json', HTTP_X_CART_ID='order-cart')
        self.assertEqual(response.status_code, 201)
        order_number = response.json()['orderNumber']

        order = Order.objects.get(order_number=order_number)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)

        settled = self.client.post(
            f'/api/orders/{order_number}/mark-received-paid',
            format='json',
            HTTP_X_CART_ID='order-cart',
        )
        self.assertEqual(settled.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.RECEIVED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_guest_can_list_orders_for_their_cart_only(self):
        self.client.post(
            '/api/orders', self.order_payload(), format='json', HTTP_X_CART_ID='order-cart')

        own = self.client.get('/api/orders', HTTP_X_CART_ID='order-cart')
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()['count'], 1)
        self.assertEqual(own.json()['results'][0]['orderNumber'],
                         Order.objects.get().order_number)

        other = self.client.get('/api/orders', HTTP_X_CART_ID='other-cart')
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()['count'], 0)

    def test_authenticated_user_lists_only_their_orders(self):
        user_a = get_user_model().objects.create_user(
            username='arnold', password='x')
        user_b = get_user_model().objects.create_user(
            username='barbara', password='x')
        cart_a = Cart.objects.create(cart_key='cart-a')
        cart_b = Cart.objects.create(cart_key='cart-b')
        customer = {'fullName': 'Arnold Buyer', 'email': 'arnold@example.com'}
        Order.objects.create(
            order_number='AT-A-0001', cart=cart_a, user=user_a,
            customer=customer, subtotal_minor=1000, total_minor=1160)
        Order.objects.create(
            order_number='AT-B-0001', cart=cart_b, user=user_b,
            customer=customer, subtotal_minor=1000, total_minor=1160)

        self.client.force_login(user_a)
        response = self.client.get('/api/orders')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['orderNumber'], 'AT-A-0001')

        self.client.logout()
        self.client.force_login(user_b)
        response = self.client.get('/api/orders')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(
            response.json()['results'][0]['orderNumber'], 'AT-B-0001')
