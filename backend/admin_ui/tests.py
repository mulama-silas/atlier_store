from io import BytesIO

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from unittest.mock import patch
from PIL import Image
from rest_framework.test import APIClient

from audit.models import AuditLog
from catalog.models import Category, Product, ProductVariant
from orders.models import Order, OrderItem
from admin_ui.models import AdminNotification, CustomerNotification
from access_control.models import Permission, StaffProfile


def enroll_staff(user, codes=None):
    """Give ``user`` explicit in-DB admin privileges under access_control
    (roles plus direct permissions). Staff that are not enrolled here are
    denied on every permission-gated admin page by design."""
    profile, _ = StaffProfile.objects.get_or_create(user=user)
    profile.status = StaffProfile.Status.ACTIVE
    if codes is None:
        profile.direct_permissions.set(Permission.objects.all())
    else:
        profile.direct_permissions.set(
            [Permission.objects.get(code=code) for code in codes])
    profile.save(update_fields=['status'])
    return profile


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username='dashboard-staff', password='test-password', email='staff@example.com')
        self.category = Category.objects.create(name='Dresses', slug='dresses')

    def test_root_redirects_to_admin_landing_page(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, '/admin/dashboard/landing/', fetch_redirect_response=False)

    def test_dashboard_requires_staff_session(self):
        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)

    def test_staff_can_render_dashboard(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Good morning.')

    def test_staff_without_product_permission_cannot_post_dashboard_mutation(self):
        staff = get_user_model().objects.create_user(
            username='limited-dashboard-staff', password='pw', is_staff=True)
        self.client.force_login(staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'create-product', 'name': 'Injected product',
        })

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.filter(name='Injected product').exists())

    def test_dashboard_recent_orders_show_total_amount(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='recent-order-total-cart')
        Order.objects.create(
            order_number='AT-RECENT-TOTAL-001',
            cart=cart,
            customer={'fullName': 'Recent Buyer',
                      'email': 'recent@example.com'},
            subtotal_minor=1200,
            total_minor=1450,
            shipping_cost_minor=250,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KES 14.50')

    def test_staff_can_see_approve_button_for_pay_on_delivery_order(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='pay-on-delivery-approve-cart')
        order = Order.objects.create(
            order_number='AT-PAY-ON-DELIVERY-001',
            cart=cart,
            customer={'fullName': 'Delivery Buyer',
                      'email': 'delivery@example.com'},
            subtotal_minor=1000,
            total_minor=1500,
            shipping_cost_minor=500,
            payment_method='pay_on_delivery',
            payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING,
        )

        self.client.force_login(self.staff)
        response = self.client.get(f'/admin/dashboard/orders/{order.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Approve & confirm order')

    def test_order_creation_creates_admin_notification(self):
        product = Product.objects.create(
            category=self.category,
            name='Notification Product',
            slug='notification-product',
            description='A product used for the order notification test.',
            price_minor=1500,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product, sku='NOTIFY-001', stock_quantity=5)

        client = APIClient()
        with self.captureOnCommitCallbacks(execute=True):
            client.post(
                '/api/cart/items',
                {'variantId': str(variant.id), 'quantity': 1},
                format='json', HTTP_X_CART_ID='notification-order-cart')
            response = client.post(
                '/api/orders',
                {
                    'customer': {
                        'fullName': 'Notification Buyer',
                        'email': 'notify@example.com',
                        'phone': '0712345678',
                        'addressLine1': '1 Market Street',
                        'city': 'Nairobi',
                        'county': 'Nairobi',
                    },
                    'shippingMethod': 'standard',
                    'paymentMethod': 'mpesa',
                },
                format='json', HTTP_X_CART_ID='notification-order-cart',
            )
        self.assertEqual(response.status_code, 201)

        notification = AdminNotification.objects.filter(
            category='order',
            title='Order placed',
            event_type='order_created',
        ).order_by('-created_at').first()

        self.assertIsNotNone(notification)
        self.assertIsNotNone(notification.audit_log)
        self.assertIn('Notification Buyer', notification.message)

    def test_dashboard_renders_pending_revenue_kpi_without_counting_pending_orders_in_total_revenue(self):
        from cart.models import Cart

        pending_cart = Cart.objects.create(cart_key='pending-revenue-kpi-cart')
        Order.objects.create(
            order_number='AT-PENDING-REVENUE-001',
            cart=pending_cart,
            customer={'fullName': 'Pending Revenue Buyer',
                      'email': 'pending@example.com'},
            subtotal_minor=1000,
            total_minor=1100,
            shipping_cost_minor=100,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING,
        )
        approved_cart = Cart.objects.create(
            cart_key='approved-revenue-kpi-cart')
        Order.objects.create(
            order_number='AT-APPROVED-REVENUE-001',
            cart=approved_cart,
            customer={'fullName': 'Approved Revenue Buyer',
                      'email': 'approved@example.com'},
            subtotal_minor=1000,
            total_minor=1500,
            shipping_cost_minor=500,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )

        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        # The label is the KPI's own "Pending revenue" chip. It previously
        # matched "Pending Revenue" only because the removed recent-orders panel
        # echoed this order's customer fullName -- the assertion was coupled to
        # the demo data rather than to the KPI it is meant to test.
        self.assertContains(response, 'Pending revenue')
        self.assertContains(response, 'KES 11')
        self.assertContains(response, 'KES 15')

    def test_dashboard_renders_unread_admin_notifications(self):
        AdminNotification.objects.create(
            recipient=self.staff,
            category='payment',
            title='Payment received',
            message='Payment received for order AT-PAID-001.',
            link='/admin/dashboard/orders/',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment received')
        self.assertContains(response, 'notification-badge')

    def test_notification_can_be_marked_read(self):
        notification = AdminNotification.objects.create(
            recipient=self.staff,
            category='order',
            title='Order placed',
            message='Order AT-READ-001 was placed.',
            link='/admin/dashboard/orders/',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/notifications/{notification.pk}/read/')

        self.assertEqual(response.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_unread_admin_notifications_api_returns_recent_alerts(self):
        AdminNotification.objects.create(
            recipient=self.staff,
            category='payment',
            title='Payment received',
            message='Payment received for order AT-PAID-001.',
            link='/admin/dashboard/orders/',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/notifications/unread/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(
            response.json()['results'][0]['title'], 'Payment received')

    def test_unread_admin_notifications_report_presented_flag(self):
        notification = AdminNotification.objects.create(
            recipient=self.staff,
            category='order',
            title='Order placed',
            message='Order AT-PRESENTED-FLAG-001 was placed.',
            link='/admin/dashboard/orders/',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/notifications/unread/')

        self.assertEqual(response.status_code, 200)
        result = response.json()['results'][0]
        self.assertEqual(result['id'], str(notification.pk))
        self.assertIs(result['presented'], False)

    def test_admin_presented_is_idempotent_and_keeps_unread(self):
        notification = AdminNotification.objects.create(
            recipient=self.staff,
            category='order',
            title='Order placed',
            message='Order AT-PRESENT-001 was placed.',
            link='/admin/dashboard/orders/',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            '/admin/dashboard/notifications/presented/',
            data=json.dumps({'ids': [str(notification.pk)]}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [str(notification.pk)])

        notification.refresh_from_db()
        self.assertIsNotNone(notification.presented_at)
        self.assertFalse(notification.is_read)

        # A second claim (another tab, refresh, or later poll) is a no-op.
        response = self.client.post(
            '/admin/dashboard/notifications/presented/',
            data=json.dumps({'ids': [str(notification.pk)]}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [])

    def test_admin_presented_is_recipient_isolated(self):
        other_staff = get_user_model().objects.create_superuser(
            username='other-presented-staff', password='test-password',
            email='other-presented@example.com',
        )
        notification = AdminNotification.objects.create(
            recipient=other_staff,
            category='order',
            title='Order placed for other admin',
            message='Other admin only.',
            is_read=False,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            '/admin/dashboard/notifications/presented/',
            data=json.dumps({'ids': [str(notification.pk)]}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [])
        notification.refresh_from_db()
        self.assertIsNone(notification.presented_at)

    def test_admin_unread_remains_visible_and_unread_after_presented(self):
        notification = AdminNotification.objects.create(
            recipient=self.staff,
            category='payment',
            title='Payment received',
            message='Payment received for order AT-PRESENT-UNREAD-001.',
            is_read=False,
        )
        self.client.force_login(self.staff)
        self.client.post(
            '/admin/dashboard/notifications/presented/',
            data=json.dumps({'ids': [str(notification.pk)]}),
            content_type='application/json',
        )

        response = self.client.get('/admin/dashboard/notifications/unread/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['unread_count'], 1)
        self.assertTrue(payload['results'][0]['presented'])
        self.assertEqual(payload['results'][0]['id'], str(notification.pk))

    def test_admin_mark_read_is_idempotent(self):
        notification = AdminNotification.objects.create(
            recipient=self.staff,
            category='order',
            title='Order placed',
            message='Order AT-READ-IDEMPOTENT-001 was placed.',
            is_read=False,
        )
        self.client.force_login(self.staff)

        first = self.client.post(
            f'/admin/dashboard/notifications/{notification.pk}/read/')
        notification.refresh_from_db()
        read_at_first = notification.read_at
        self.assertIsNotNone(read_at_first)

        second = self.client.post(
            f'/admin/dashboard/notifications/{notification.pk}/read/')
        notification.refresh_from_db()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(notification.is_read)
        self.assertEqual(notification.read_at, read_at_first)

    def test_admin_mark_all_read_clears_unread_even_when_presented(self):
        from django.utils import timezone

        already_presented = AdminNotification.objects.create(
            recipient=self.staff, category='order', title='A',
            message='A message', is_read=False, presented_at=timezone.now())
        AdminNotification.objects.create(
            recipient=self.staff, category='payment', title='B',
            message='B message', is_read=False)
        self.client.force_login(self.staff)

        response = self.client.post(
            '/admin/dashboard/notifications/read-all/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 0)
        self.assertEqual(
            AdminNotification.objects.filter(
                recipient=self.staff, is_read=False).count(), 0)
        already_presented.refresh_from_db()
        self.assertIsNotNone(already_presented.presented_at)

    def test_admin_order_notification_route_does_not_crash(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='order-notification-route-cart')
        order = Order.objects.create(
            order_number='AT-NOTIFICATION-ROUTE-001',
            cart=cart,
            customer={'fullName': 'Route Buyer', 'email': 'route@example.com'},
            subtotal_minor=1200,
            total_minor=1500,
            shipping_cost_minor=300,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/orders/{order.pk}/')

        self.assertEqual(response.status_code, 200)

    def test_order_approval_notifies_customer(self):
        from cart.models import Cart
        from orders.services import approve_order

        user = get_user_model().objects.create_user(
            username='approved-customer',
            email='approved.customer@example.com',
            password='test-password',
        )
        cart = Cart.objects.create(cart_key='order-approval-notify-cart')
        order = Order.objects.create(
            order_number='AT-ORDER-APPROVAL-NOTIFY-001',
            cart=cart,
            user=user,
            customer={'fullName': 'Approved Buyer',
                      'email': 'approved.customer@example.com'},
            subtotal_minor=1200,
            total_minor=1500,
            shipping_cost_minor=300,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PENDING,
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_order(order)

        notification = CustomerNotification.objects.filter(
            user=user,
            title='Order confirmed',
        ).order_by('-created_at').first()

        self.assertIsNotNone(notification)
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertIn(order.order_number, notification.message)

        staff_notification = AdminNotification.objects.filter(
            category='order',
            title='Order confirmed',
            event_type='order_confirmed',
            message__icontains=order.order_number,
        ).first()
        self.assertIsNotNone(staff_notification)
        self.assertIsNotNone(staff_notification.audit_log)

    def test_low_stock_creates_admin_notification(self):
        product = Product.objects.create(
            category=self.category,
            name='Low Stock Product',
            slug='low-stock-product',
            description='Needs restock soon.',
            price_minor=15000,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=product,
            sku='LOW-STOCK-001',
            size='M',
            color='Black',
            stock_quantity=2,
        )

        notification = AdminNotification.objects.filter(
            category='inventory',
            title='Low stock alert',
        ).order_by('-created_at').first()

        self.assertIsNotNone(notification)
        self.assertIn('Low Stock Product', notification.message)

    def test_customer_notification_is_created_for_order(self):
        user = get_user_model().objects.create_user(
            username='customer-order-notify',
            email='customer@example.com',
            password='test-password',
        )
        Cart = __import__('cart.models', fromlist=['Cart']).Cart
        cart = Cart.objects.create(cart_key='notification-customer-cart')
        order = Order.objects.create(
            order_number='AT-CUSTOMER-NOTIFY-001',
            cart=cart,
            user=user,
            customer={'fullName': 'Customer Alert',
                      'email': 'customer@example.com'},
            subtotal_minor=1200,
            total_minor=1500,
            shipping_cost_minor=300,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING,
        )

        notification = CustomerNotification.objects.filter(
            user=user,
            title='Order placed',
        ).order_by('-created_at').first()

        self.assertIsNotNone(notification)
        self.assertIn('AT-CUSTOMER-NOTIFY-001', notification.message)
        self.assertEqual(notification.link,
                         f'/account/orders/{order.order_number}')

    def test_customer_notifications_endpoint_returns_user_items(self):
        user = get_user_model().objects.create_user(
            username='customer-notifications',
            email='customer.notifications@example.com',
            password='test-password',
        )
        CustomerNotification.objects.create(
            user=user,
            category='order',
            title='Order placed',
            message='Your order AT-API-001 has been placed.',
            link='/account/orders',
            is_read=False,
        )
        self.client.force_login(user)

        response = self.client.get('/api/notifications')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(
            response.json()['results'][0]['title'], 'Order placed')

    def test_dashboard_sales_overview_uses_real_order_data(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='sales-overview-cart')
        Order.objects.create(
            order_number='AT-SALES-OVERVIEW-001',
            cart=cart,
            customer={'fullName': 'Sales Buyer', 'email': 'sales@example.com'},
            subtotal_minor=2000,
            total_minor=2200,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.DELIVERED,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sales-chart-point')
        self.assertContains(response, 'data-value="22.00"')

    def test_customers_page_excludes_staff_users(self):
        staff = get_user_model().objects.create_user(
            username='staff-not-customer', email='staff@example.com', is_staff=True)
        customer = get_user_model().objects.create_user(
            username='real-customer', email='customer@example.com')
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/customers/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, customer.username)
        self.assertNotContains(response, staff.username)

    def test_dashboard_customer_count_excludes_staff_users(self):
        get_user_model().objects.create_user(
            username='counted-customer', email='counted@example.com')
        get_user_model().objects.create_user(
            username='counted-staff', email='staff-count@example.com', is_staff=True)
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="metric-value">1</div>')

    def test_dashboard_sales_overview_range_selector_changes_period(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/', {'range': '30'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="30" selected')
        self.assertContains(response, '1 Month')

    def test_staff_can_render_products_page_spec(self):
        self.client.force_login(self.staff)
        product_one = Product.objects.create(
            category=self.category,
            name='MODEZA Silk Wrap Dress',
            slug='modeza-silk-wrap-dress',
            description='A refined evening silhouette.',
            price_minor=480000,
            status=Product.Status.ACTIVE,
            images=['/media/products/modeza-silk-dress.jpg'],
        )
        product_two = Product.objects.create(
            category=self.category,
            name='Eva Linen Set',
            slug='eva-linen-set',
            description='Relaxed daily wear.',
            price_minor=395000,
            status=Product.Status.ACTIVE,
            images=['/media/products/eva-linen-set.jpg'],
        )

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Products')
        self.assertContains(response, 'Checkbox')
        self.assertContains(response, 'Product Image')
        self.assertContains(response, 'Product Name')
        self.assertContains(response, 'Category')
        self.assertContains(response, 'Price')
        self.assertContains(response, 'Stock')
        self.assertContains(response, 'Status')
        self.assertContains(response, 'Actions')
        self.assertContains(response, 'View')
        self.assertContains(response, 'Edit')
        self.assertContains(response, 'Duplicate')
        self.assertContains(response, 'Archive')
        self.assertContains(response, 'Delete')
        self.assertContains(response, product_one.name)
        self.assertContains(response, product_two.name)
        self.assertContains(response, 'admin-product-thumb')

    def test_admin_products_page_paginates_and_preserves_search(self):
        for index in range(26):
            Product.objects.create(
                category=self.category,
                name=f'Pagination product {index}',
                slug=f'pagination-product-{index}',
                description='Created for admin pagination coverage.',
                price_minor=10000,
                status=Product.Status.ACTIVE,
            )
        self.client.force_login(self.staff)

        first_page = self.client.get(
            '/admin/dashboard/products/', {'q': 'Pagination'})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(
            first_page.context['page_data']['products_page'].paginator.count,
            26,
        )
        self.assertContains(first_page, 'Showing 1 to 25')
        self.assertContains(first_page, 'of 26 products')
        self.assertContains(first_page, 'Page 1 of 2')
        self.assertContains(first_page, '?q=Pagination&amp;page=2')

        second_page = self.client.get(
            '/admin/dashboard/products/', {'q': 'Pagination', 'page': '2'})

        self.assertEqual(second_page.status_code, 200)
        self.assertContains(second_page, 'Showing 26 to 26')
        self.assertContains(second_page, 'of 26 products')
        self.assertContains(second_page, 'Page 2 of 2')
        self.assertContains(second_page, '?q=Pagination&amp;page=1')

    def test_products_page_renders_real_database_records(self):
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Database Verified Product',
            slug='database-verified-product',
            description='Created in the database for verification.',
            price_minor=15000,
            status=Product.Status.ACTIVE,
            images=['/media/products/database-verified-product.png'],
        )

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.name)
        self.assertContains(response, product.images[0])

    def test_variants_page_renders_real_variant_records(self):
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Variants Page Product',
            slug='variants-page-product',
            description='Used to verify the dedicated variants page.',
            price_minor=25000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku='VP-XS',
            size='XS',
            color='Olive',
            price_minor=12500,
            stock_quantity=5,
        )
        ProductVariant.objects.create(
            product=product,
            sku='VP-M',
            size='M',
            color='Black',
            price_minor=12500,
            stock_quantity=2,
        )

        response = self.client.get('/admin/dashboard/variants/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product Variants')
        self.assertContains(response, 'Add Variant')
        self.assertContains(response, '/admin/dashboard/variants/new/')
        self.assertContains(response, product.name)
        self.assertContains(response, 'VP-XS')
        self.assertContains(response, 'VP-M')
        self.assertContains(response, variant.id)
        self.assertContains(response, 'Restock')
        self.assertContains(
            response, f'/admin/dashboard/inventory/adjust/?variant={variant.id}')

    def test_variant_product_picker_lists_products_and_links_to_new_variant_form(self):
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Picker Target Product',
            slug='picker-target-product',
            description='Picked before adding a variant.',
            price_minor=30000,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=product, sku='PK-XS', size='XS', stock_quantity=3)

        response = self.client.get('/admin/dashboard/variants/new/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Variant')
        self.assertContains(response, product.name)
        self.assertContains(
            response,
            f'/admin/dashboard/products/{product.id}/variants/new/')

        form_response = self.client.get(
            f'/admin/dashboard/products/{product.id}/variants/new/')

        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'Add variant')

    def test_products_page_includes_checkbox_column_data(self):
        self.client.force_login(self.staff)
        Product.objects.create(
            category=self.category,
            name='Checkbox Row Product',
            slug='checkbox-row-product',
            description='Row should include a checkbox field.',
            price_minor=25000,
            status=Product.Status.ACTIVE,
        )

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="admin-row-check"')

    def test_product_row_actions_have_working_links(self):
        """Each product row exposes working actions.

        The row UI is a <details> disclosure, not a <select> dropdown. The
        earlier version of this test expected a dropdown that only ever rendered
        in the empty state, with every option pointing at /products/new/ -- so it
        asserted UI that could not work. These assertions cover the links that
        are actually emitted.
        """
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Action Dropdown Product',
            slug='action-dropdown-product',
            description='This row should expose working actions.',
            price_minor=9000,
            status=Product.Status.ACTIVE,
        )

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'href="/admin/dashboard/products/{product.id}/"')
        self.assertContains(
            response, f'href="/admin/dashboard/products/{product.id}/edit/"')
        self.assertContains(
            response, f'href="/admin/dashboard/products/{product.id}/duplicate/"')
        self.assertContains(
            response,
            f'href="/admin/dashboard/confirm/?action=delete-product&product_id={product.id}"')

    @patch('admin_ui.views.ProductGenerationService.generate_product_metadata')
    def test_add_product_generates_metadata_and_internal_code(self, generate_metadata):
        generate_metadata.return_value = {
            'description': 'A polished silk dress for evening occasions.',
            'slug': 'luna-silk-dress',
        }
        self.client.force_login(self.staff)
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='blue').save(image_buffer, format='PNG')

        response = self.client.post('/admin/dashboard/products/new/', {
            'name': 'Luna Silk Dress',
            'category': str(self.category.id),
            'price': '2450',
            'status': 'ACTIVE',
            'sku': '',
            'size': 'M',
            'color': 'Ivory',
            'stock_quantity': '5',
            'image_file': SimpleUploadedFile(
                'luna.png', image_buffer.getvalue(), content_type='image/png'),
        })

        self.assertRedirects(response, '/admin/dashboard/')
        product = Product.objects.get(slug='luna-silk-dress')
        variant = product.variants.get()
        self.assertEqual(product.description,
                         'A polished silk dress for evening occasions.')
        self.assertEqual(variant.sku, 'AT-LUNA-SILK-DRESS')
        generate_metadata.assert_called_once_with(
            'Luna Silk Dress')

    def test_staff_products_page_renders_product_model_image(self):
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Linen Wrap Top',
            slug='linen-wrap-top',
            description='A breathable wrap top for softer styling.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
            images=['/media/products/test-product-image.png'],
        )

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.name)
        self.assertContains(response, product.images[0])

    def test_staff_pages_render_single_string_product_images(self):
        self.client.force_login(self.staff)
        product = Product.objects.create(
            category=self.category,
            name='Single String Image Product',
            slug='single-string-image-product',
            description='This product stores its image as a single string.',
            price_minor=18000,
            status=Product.Status.ACTIVE,
            images='/media/products/string-image.png',
        )

        list_response = self.client.get('/admin/dashboard/products/')
        detail_response = self.client.get(
            f'/admin/dashboard/products/{product.id}/')

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, '/media/products/string-image.png')
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(
            detail_response, '/media/products/string-image.png')

    def test_staff_product_names_are_clickable_links_to_detail_page(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Wrap Top',
            slug='linen-wrap-top-link',
            description='A breathable wrap top for softer styling.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="/admin/dashboard/products/{product.id}/"',
            html=False,
        )
        self.assertContains(response, product.name)

    def test_staff_can_search_products_by_name(self):
        Product.objects.create(
            category=self.category,
            name='Silk Evening Gown',
            slug='silk-evening-gown',
            description='A refined evening silhouette.',
            price_minor=18000,
            status=Product.Status.ACTIVE,
        )
        Product.objects.create(
            category=self.category,
            name='Cotton Travel Tee',
            slug='cotton-travel-tee',
            description='Relaxed daily wear.',
            price_minor=9000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/products/', {'q': 'Evening'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Silk Evening Gown')
        self.assertNotContains(response, 'Cotton Travel Tee')

    def test_staff_products_empty_state_offers_create_action(self):
        """Empty products page offers the real action, not a broken dropdown.

        The empty state previously rendered a View/Edit/Duplicate/Archive/Delete
        dropdown in which every option pointed at /products/new/ -- offering to
        archive or delete rows that do not exist. It now just offers the create
        button, which is the only meaningful action with no rows.
        """
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/admin/dashboard/products/new/')
        self.assertNotContains(response, 'class="admin-action-select"')

    def test_staff_can_open_create_product_page(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/new/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add a product')

    def test_staff_can_open_product_import_page_in_dashboard(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/import/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bulk Product Import')

    def test_staff_can_bulk_import_products(self):
        self.client.force_login(self.staff)
        csv_data = (
            'name,price,category,sku,stock_quantity\n'
            'Luna Silk Dress,2450,Dresses,SKU-LUNA-001,10\n'
        )

        response = self.client.post(
            '/admin/dashboard/products/import/',
            {
                'file': SimpleUploadedFile(
                    'products.csv', csv_data.encode('utf-8'), content_type='text/csv'),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import complete: 1 rows succeeded')
        self.assertTrue(Product.objects.filter(sku='SKU-LUNA-001').exists())

    def test_staff_can_open_product_detail_page(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Top',
            slug='linen-top',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                f'/admin/dashboard/products/{product.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product Details')
        self.assertContains(response, 'Linen Top')
        self.assertTrue(AuditLog.objects.filter(
            action='product_viewed', object_id=str(product.id),
            metadata__surface='admin_product_detail',
        ).exists())

    def test_staff_can_add_variant_and_restock_from_product_detail_page(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Top',
            slug='linen-top-restock',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product,
            sku='LINEN-TOP-RESTOCK',
            stock_quantity=4,
        )
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/products/{product.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add variant')
        self.assertContains(
            response, f'/admin/dashboard/products/{product.id}/variants/new/')
        self.assertContains(response, 'Restock')

        restock_response = self.client.post(
            '/admin/dashboard/inventory/adjust/',
            {'variant': str(variant.id), 'delta': 7, 'reason': 'restock'},
            follow=True,
        )

        self.assertEqual(restock_response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 11)

    def test_staff_can_open_edit_product_page(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Top',
            slug='linen-top',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                f'/admin/dashboard/products/{product.id}/edit/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Linen Top')

    def test_staff_can_create_edit_and_delete_product_variant(self):
        product = Product.objects.create(
            category=self.category,
            name='Variant Product',
            slug='variant-product',
            description='A product with multiple options.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        create_response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/new/',
            {
                'sku': 'VARIANT-001',
                'size': 'M',
                'color': 'Forest',
                'color_hex': '#2E5A44',
                'price': '135.50',
                'stock_quantity': '8',
                'is_active': 'on',
            },
        )

        self.assertRedirects(
            create_response, f'/admin/dashboard/products/{product.id}/')
        variant = ProductVariant.objects.get(sku='VARIANT-001')
        self.assertEqual(variant.price_minor, 13550)
        self.assertEqual(variant.stock_quantity, 8)

        edit_response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/{variant.id}/edit/',
            {
                'sku': 'VARIANT-001-UPDATED',
                'size': 'L',
                'color': 'Forest',
                'color_hex': '#2E5A44',
                'price': '140.00',
                'stock_quantity': '10',
                'is_active': 'on',
            },
        )

        self.assertRedirects(
            edit_response, f'/admin/dashboard/products/{product.id}/')
        variant.refresh_from_db()
        self.assertEqual(variant.sku, 'VARIANT-001-UPDATED')
        self.assertEqual(variant.size, 'L')

        delete_response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/{variant.id}/delete/')
        self.assertRedirects(
            delete_response, f'/admin/dashboard/products/{product.id}/')
        variant.refresh_from_db()
        self.assertFalse(variant.is_active)
        self.assertEqual(
            ProductVariant.objects.filter(pk=variant.id).count(), 1)

    def test_staff_can_delete_variant_without_history(self):
        product = Product.objects.create(
            category=self.category,
            name='Delete Product',
            slug='delete-product',
            description='A product whose fresh variant can be removed.',
            price_minor=9000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product, sku='DELETE-PRODUCT-M', size='M')
        self.client.force_login(self.staff)

        delete_response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/{variant.id}/delete/')
        self.assertRedirects(
            delete_response, f'/admin/dashboard/products/{product.id}/')
        self.assertFalse(ProductVariant.objects.filter(pk=variant.id).exists())

    def test_variant_form_rejects_duplicate_product_options(self):
        product = Product.objects.create(
            category=self.category,
            name='Duplicate Variant Product',
            slug='duplicate-variant-product',
            description='A product with duplicate option protection.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=product, sku='DUPLICATE-001', size='M', color='Black')
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/new/',
            {
                'sku': 'DUPLICATE-002',
                'size': 'M',
                'color': 'Black',
                'price': '',
                'stock_quantity': '4',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'This size and colour combination already exists')
        self.assertFalse(ProductVariant.objects.filter(
            sku='DUPLICATE-002').exists())

    def test_staff_can_bulk_create_size_variants_with_quantities(self):
        product = Product.objects.create(
            category=self.category,
            name='Size Matrix Product',
            slug='size-matrix-product',
            description='A product with a size matrix.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/bulk/',
            {
                'color': 'Black', 'color_hex': '#111111', 'price': '120.00',
                'size_1': 'Small', 'quantity_1': '4',
                'size_2': 'Medium', 'quantity_2': '7',
                'size_3': 'Large', 'quantity_3': '2',
            },
        )

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variants = ProductVariant.objects.filter(
            product=product).order_by('size')
        self.assertEqual(variants.count(), 3)
        self.assertEqual(
            {variant.size: variant.stock_quantity for variant in variants},
            {'Small': 4, 'Medium': 7, 'Large': 2},
        )
        self.assertEqual(
            {variant.sku for variant in variants},
            {'SIZE-MATRIX-PRODUCT-SMALL-BLACK',
             'SIZE-MATRIX-PRODUCT-MEDIUM-BLACK',
             'SIZE-MATRIX-PRODUCT-LARGE-BLACK'},
        )

    def test_bulk_variant_sku_collision_gets_numeric_suffix(self):
        product = Product.objects.create(
            category=self.category,
            name='Collision Product',
            slug='collision-product',
            description='A product for SKU collision handling.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=product, sku='COLLISION-PRODUCT-S-M-BLACK', size='SM',
            color='Black')
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/bulk/',
            {
                'color': 'Black',
                'size_1': 'S/M', 'quantity_1': '4',
            },
        )

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variants = ProductVariant.objects.filter(
            product=product).order_by('sku')
        self.assertEqual(variants.count(), 2)
        self.assertTrue(variants.filter(
            sku='COLLISION-PRODUCT-S-M-BLACK-1', size='S/M').exists())

    def test_bulk_variant_rows_colliding_on_same_sku_rejected_atomically(self):
        product = Product.objects.create(
            category=self.category,
            name='Same Sku Product',
            slug='same-sku-product',
            description='A product where two sizes share one normalized SKU.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/bulk/',
            {
                'color': 'Black',
                'size_1': 'S/M', 'quantity_1': '4',
                'size_2': 'S-M', 'quantity_2': '5',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'would collide on the same SKU')
        self.assertFalse(ProductVariant.objects.filter(
            product=product).exists())

    def test_bulk_variant_duplicate_option_never_partially_creates(self):
        product = Product.objects.create(
            category=self.category,
            name='Atomic Bulk Product',
            slug='atomic-bulk-product',
            description='A product that must never get a partial size matrix.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=product, sku='ATOMIC-BULK-PRODUCT-M-BLACK', size='M',
            color='Black')
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/bulk/',
            {
                'color': 'Black',
                'size_1': 'S', 'quantity_1': '4',
                'size_2': 'M', 'quantity_2': '5',
                'size_3': 'L', 'quantity_3': '2',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'combination M already exists')
        existing = set(
            ProductVariant.objects.filter(product=product)
            .values_list('size', flat=True))
        self.assertEqual(existing, {'M'})

    def test_variant_form_normalizes_sku_and_hex(self):
        product = Product.objects.create(
            category=self.category,
            name='Normalized Product',
            slug='normalized-product',
            description='A product whose variant data gets normalized.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/new/',
            {
                'sku': '  dress/top  12 ',
                'size': 'M',
                'color': 'Forest Green',
                'color_hex': '#2e5a44',
                'price': '135.50',
                'stock_quantity': '8',
                'is_active': 'on',
            },
        )

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variant = ProductVariant.objects.get(product=product)
        self.assertEqual(variant.sku, 'DRESS-TOP-12')
        self.assertEqual(variant.color_hex, '#2E5A44')

    def test_variant_form_rejects_malformed_color_hex(self):
        product = Product.objects.create(
            category=self.category,
            name='Hex Check Product',
            slug='hex-check-product',
            description='A product that rejects bad colour hex values.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/new/',
            {
                'sku': 'HEX-CHECK-M',
                'size': 'M',
                'color': 'Not Real',
                'color_hex': '#GGGGGG',
                'price': '',
                'stock_quantity': '4',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Use a hex colour such as #2E5A44.')
        self.assertFalse(ProductVariant.objects.filter(
            product=product).exists())

    def test_bulk_generated_sku_is_truncated_to_80_characters(self):
        product = Product.objects.create(
            category=self.category,
            name='An Exceedingly Long Product Name That Keeps Going And Going',
            slug='an-exceedingly-long-product-name-that-keeps-going-and-going-and-going',
            description='A product whose generated SKUs must respect the field limit.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/bulk/',
            {
                'color': 'Charcoal Grey',
                'size_1': 'Small', 'quantity_1': '2',
            },
        )

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variant = ProductVariant.objects.get(product=product)
        self.assertLessEqual(len(variant.sku), 80)

    def test_editing_stock_writes_inventory_transaction_and_audit(self):
        from inventory.models import InventoryTransaction

        product = Product.objects.create(
            category=self.category,
            name='Stock Ledger Product',
            slug='stock-ledger-product',
            description='A product whose stock edits hit the inventory ledger.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product, sku='STOCK-LEDGER-M', size='M', stock_quantity=5)
        self.client.force_login(self.staff)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f'/admin/dashboard/products/{product.id}/variants/{variant.id}/edit/',
                {
                    'sku': 'STOCK-LEDGER-M',
                    'size': 'M',
                    'color': '',
                    'color_hex': '',
                    'price': '',
                    'stock_quantity': '12',
                    'is_active': 'on',
                },
            )

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 12)
        txn = InventoryTransaction.objects.filter(
            variant=variant, reason='variant_edit').latest('created_at')
        self.assertEqual(txn.quantity_delta, 7)
        self.assertEqual(txn.previous_quantity, 5)
        self.assertEqual(txn.new_quantity, 12)
        audit = AuditLog.objects.filter(
            object_type='productvariant', action='update',
            object_id=str(variant.pk)).order_by('-created_at').first()
        self.assertIsNotNone(audit)
        self.assertEqual(
            audit.metadata.get('before', {}).get('stock_quantity'), 5)

    def test_delete_deactivates_variant_used_in_orders(self):
        product = Product.objects.create(
            category=self.category,
            name='Used Variant Product',
            slug='used-variant-product',
            description='A product with order history protection.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product, sku='USED-VARIANT-M', size='M', stock_quantity=5)
        from cart.models import Cart
        cart = Cart.objects.create(cart_key='used-variant-cart')
        Order.objects.create(
            order_number='AT-USED-VARIANT-001',
            cart=cart,
            customer={'fullName': 'Used Variant Buyer',
                      'email': 'used-variant@example.com'},
            subtotal_minor=12000,
            shipping_cost_minor=0,
            total_minor=12000,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING,
        )
        OrderItem.objects.create(
            order=Order.objects.get(order_number='AT-USED-VARIANT-001'),
            product=product,
            variant=variant,
            product_name=product.name,
            variant_sku=variant.sku,
            variant_size='M',
            unit_price_minor=12000,
            quantity=1,
            line_total_minor=12000,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/products/{product.id}/variants/{variant.id}/delete/')

        self.assertRedirects(
            response, f'/admin/dashboard/products/{product.id}/')
        variant.refresh_from_db()
        self.assertFalse(variant.is_active)
        self.assertEqual(
            ProductVariant.objects.filter(pk=variant.id).count(), 1)
        self.assertTrue(OrderItem.objects.filter(
            variant=variant, variant_sku='USED-VARIANT-M').exists())
    def test_staff_can_open_admin_user_invite_page(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/admin-users/invite/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invite Admin')

    def test_admin_dashboard_topbar_profile_icon_targets_profile_page(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertEqual(response.status_code, 200)
        # The sidebar footer and the topbar avatar both link to the profile
        # page, so counting page-wide occurrences is not meaningful. Assert the
        # avatar itself points at it, which is what this test is actually for.
        self.assertContains(
            response,
            'href="/admin/dashboard/profile/" class="admin-avatar"',
            count=1)
        self.assertContains(response, 'admin-avatar')

    def test_staff_can_open_profile_settings_page(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/profile/settings/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My Profile')

    def test_staff_categories_page_row_actions_are_rendered(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/categories/')

        self.assertEqual(response.status_code, 200)
        # Row actions are a <details> disclosure; the old assertion expected an
        # admin-action-select dropdown that was gated to page == 'products' and
        # so could never render here.
        self.assertContains(
            response, f'href="/admin/dashboard/categories/{self.category.id}/edit/"')
        self.assertContains(
            response, f'href="/admin/dashboard/categories/{self.category.id}/delete/"')

    def test_staff_can_open_stock_adjustment_page(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/inventory/adjust/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update availability')

    def test_admin_orders_page_renders_real_orders_from_database(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='order-admin-cart')
        order = Order.objects.create(
            order_number='AT-ORDER-ADMIN-001',
            cart=cart,
            customer={'full_name': 'Jane Doe', 'email': 'jane@example.com'},
            subtotal_minor=1200,
            total_minor=1400,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/orders/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)
        self.assertContains(response, 'Jane Doe')
        self.assertContains(response, 'Paid')

    def test_admin_orders_dropdown_can_confirm_pending_paid_order(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='order-admin-dropdown-cart')
        order = Order.objects.create(
            order_number='AT-ORDER-ADMIN-DROPDOWN-001',
            cart=cart,
            customer={'full_name': 'Jane Doe', 'email': 'jane@example.com'},
            subtotal_minor=1200,
            total_minor=1400,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PENDING,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/orders/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="/admin/dashboard/orders/{order.id}/"',
        )
        self.assertContains(
            response,
            f'action="/admin/dashboard/orders/{order.id}/approve/"',
        )
        self.assertContains(response, 'Confirm order')

    def test_staff_can_filter_orders_by_status_and_payment_status(self):
        from cart.models import Cart

        paid_processing_cart = Cart.objects.create(
            cart_key='order-filter-paid-processing')
        pending_cart = Cart.objects.create(cart_key='order-filter-pending')
        Order.objects.create(
            order_number='AT-ORDER-FILTER-PAID',
            cart=paid_processing_cart,
            customer={'fullName': 'Alice Buyer', 'email': 'alice@example.com'},
            subtotal_minor=1200,
            total_minor=1400,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        Order.objects.create(
            order_number='AT-ORDER-FILTER-PENDING',
            cart=pending_cart,
            customer={'fullName': 'Bob Buyer', 'email': 'bob@example.com'},
            subtotal_minor=2000,
            total_minor=2200,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PENDING,
            status=Order.Status.PENDING,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/orders/', {
            'status': Order.Status.PROCESSING,
            'payment_status': Order.PaymentStatus.PAID,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AT-ORDER-FILTER-PAID')
        self.assertNotContains(response, 'AT-ORDER-FILTER-PENDING')

    def test_staff_can_approve_paid_order(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='order-admin-approve-cart')
        order = Order.objects.create(
            order_number='AT-ORDER-ADMIN-APPROVE-001',
            cart=cart,
            customer={'fullName': 'Jane Doe', 'email': 'jane@example.com'},
            subtotal_minor=1200,
            total_minor=1400,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PENDING,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/orders/{order.id}/approve/', follow=True)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertContains(response, 'Order approved')

    def _approveable_order(self, cart_key, order_number):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key=cart_key)
        return Order.objects.create(
            order_number=order_number,
            cart=cart,
            customer={'fullName': 'Jane Doe', 'email': 'jane@example.com'},
            subtotal_minor=1200,
            total_minor=1400,
            shipping_cost_minor=200,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PENDING,
        )

    def test_an_unexpected_approve_error_is_logged_not_mislabelled(self):
        """The old bare ``except Exception`` reported every failure as "only
        paid orders can be approved", sending operators after a problem the
        order did not have."""
        from unittest.mock import patch

        order = self._approveable_order(
            'order-admin-approve-boom-cart', 'AT-ORDER-APPROVE-BOOM-001')
        self.client.force_login(self.staff)

        with patch('admin_ui.views.approve_order',
                   side_effect=RuntimeError('receipt blew up')):
            with self.assertLogs('admin_ui.views', level='ERROR') as caught:
                response = self.client.post(
                    f'/admin/dashboard/orders/{order.id}/approve/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'check the server logs')
        self.assertNotContains(response, 'Only paid orders can be approved.')
        self.assertTrue(
            any('receipt blew up' in line for line in caught.output))

    def test_the_real_validation_message_reaches_the_operator(self):
        from unittest.mock import patch
        from rest_framework.exceptions import ValidationError as DRFValidationError

        order = self._approveable_order(
            'order-admin-approve-invalid-cart', 'AT-ORDER-APPROVE-BAD-001')
        self.client.force_login(self.staff)

        with patch('admin_ui.views.approve_order',
                   side_effect=DRFValidationError(
                       {'status': 'Order was cancelled and cannot be paid.'})):
            response = self.client.post(
                f'/admin/dashboard/orders/{order.id}/approve/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response,
                            'Order was cancelled and cannot be paid.')
        self.assertNotContains(response, 'Only paid orders can be approved.')

    def test_error_detail_unwraps_both_validation_error_shapes(self):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from admin_ui.views import _error_detail

        self.assertEqual(
            _error_detail(DRFValidationError({'status': 'Too late.'})),
            'Too late.')
        self.assertEqual(
            _error_detail(DjangoValidationError('Too late.')), 'Too late.')
        self.assertEqual(_error_detail(RuntimeError('boom')), '')

    def test_staff_can_create_category(self):
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/categories/new/', {
            'name': 'Accessories',
            'slug': 'accessories',
            'description': 'Finishing pieces for every look.',
            'image_url': 'https://example.com/accessories.jpg',
            'is_active': 'on',
        })

        self.assertRedirects(response, '/admin/dashboard/')
        category = Category.objects.get(slug='accessories')
        self.assertEqual(category.name, 'Accessories')
        self.assertTrue(category.is_active)

    def test_staff_can_edit_category(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            f'/admin/dashboard/categories/{self.category.id}/edit/', {
                'name': 'Evening Dresses',
                'slug': 'evening-dresses',
                'description': 'After-dark silhouettes.',
                'image_url': '',
                'is_active': 'on',
            })

        self.assertRedirects(response, '/admin/dashboard/')
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Evening Dresses')
        self.assertEqual(self.category.slug, 'evening-dresses')

    def test_staff_can_delete_unused_category(self):
        category = Category.objects.create(name='Unused', slug='unused')
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'delete-category',
            'category_id': str(category.id),
        })

        self.assertRedirects(response, '/admin/dashboard/')
        self.assertFalse(Category.objects.filter(pk=category.id).exists())

    def test_staff_cannot_delete_category_used_by_product(self):
        Product.objects.create(
            category=self.category,
            name='Category Product',
            slug='category-product',
            description='A product keeping its category in use.',
            price_minor=10000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'delete-category',
            'category_id': str(self.category.id),
        }, follow=True)

        self.assertRedirects(response, '/admin/dashboard/')
        self.assertTrue(Category.objects.filter(pk=self.category.id).exists())
        self.assertContains(response, 'products still use it')

    def test_staff_can_create_product_and_variant(self):
        self.client.force_login(self.staff)
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='blue').save(image_buffer, format='PNG')
        upload = SimpleUploadedFile(
            'dress-create.png', image_buffer.getvalue(), content_type='image/png')

        response = self.client.post('/admin/dashboard/', {
            'action': 'create-product',
            'name': 'Silk Dress',
            'slug': 'silk-dress',
            'category': str(self.category.id),
            'description': 'A lightweight silk dress for evening wear.',
            'price': '245.00',
            'status': Product.Status.ACTIVE,
            'sku': 'SILK-S',
            'size': 'S',
            'color': 'Black',
            'stock_quantity': '4',
            'image_file': upload,
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        product = Product.objects.get(slug='silk-dress')
        self.assertEqual(product.price_minor, 24500)
        self.assertEqual(product.variants.get().stock_quantity, 4)

    def test_staff_can_upload_local_product_image_when_url_is_missing(self):
        self.client.force_login(self.staff)
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='red').save(image_buffer, format='PNG')
        upload = SimpleUploadedFile(
            'dress-upload.png',
            image_buffer.getvalue(),
            content_type='image/png',
        )

        response = self.client.post('/admin/dashboard/', {
            'action': 'create-product',
            'name': 'Silk Dress Upload',
            'slug': 'silk-dress-upload',
            'category': str(self.category.id),
            'description': 'An evening dress that can be uploaded locally without a remote URL.',
            'price': '260.00',
            'status': Product.Status.ACTIVE,
            'sku': 'UPLOAD-S',
            'size': 'M',
            'color': 'Ivory',
            'stock_quantity': '2',
            'image_file': upload,
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        product = Product.objects.get(slug='silk-dress-upload')
        self.assertEqual(len(product.images), 1)
        self.assertIn('/media/products/', product.images[0])
        self.assertTrue(product.images[0].endswith('.png'))

    def test_staff_can_update_product_from_dashboard(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Top',
            slug='linen-top',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'update-product',
            'product_id': str(product.id),
            'name': 'Linen Top Updated',
            'slug': 'linen-top-updated',
            'category': str(self.category.id),
            'description': 'Updated linen top description for the shop.',
            'price': '149.00',
            'status': Product.Status.ACTIVE,
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        product.refresh_from_db()
        self.assertEqual(product.name, 'Linen Top Updated')
        self.assertEqual(product.slug, 'linen-top-updated')
        self.assertEqual(product.price_minor, 14900)

    def test_staff_can_archive_product_from_dashboard(self):
        product = Product.objects.create(
            category=self.category,
            name='Archived Dress',
            slug='archived-dress',
            description='A dress that is being archived from the collection.',
            price_minor=11000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'archive-product',
            'product_id': str(product.id),
        })

        # Catalogue actions live on the products page now that the dashboard is
        # KPI cards only, so the view sends the operator there.
        self.assertRedirects(response, '/admin/dashboard/products/')
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.ARCHIVED)

    def test_staff_can_delete_product_from_dashboard(self):
        product = Product.objects.create(
            category=self.category,
            name='Delete Me Dress',
            slug='delete-me-dress',
            description='A product that can be removed from the catalogue.',
            price_minor=11000,
            status=Product.Status.DRAFT,
        )
        product_id = product.id
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'delete-product',
            'product_id': str(product_id),
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        self.assertFalse(Product.objects.filter(pk=product_id).exists())

    def test_staff_can_delete_multiple_selected_products_from_dashboard(self):
        first = Product.objects.create(
            category=self.category,
            name='Delete Me First',
            slug='delete-me-first',
            description='Should be deleted in bulk.',
            price_minor=11000,
            status=Product.Status.DRAFT,
        )
        second = Product.objects.create(
            category=self.category,
            name='Delete Me Second',
            slug='delete-me-second',
            description='Also should be deleted in bulk.',
            price_minor=12000,
            status=Product.Status.DRAFT,
        )
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'delete-selected-products',
            'product_ids': [str(first.id), str(second.id)],
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        self.assertFalse(Product.objects.filter(
            pk__in=[first.id, second.id]).exists())

    def test_staff_can_view_confirmation_page_for_bulk_delete(self):
        first = Product.objects.create(
            category=self.category,
            name='Delete Me First',
            slug='delete-me-first-confirm',
            description='Should be deleted in bulk.',
            price_minor=11000,
            status=Product.Status.DRAFT,
        )
        second = Product.objects.create(
            category=self.category,
            name='Delete Me Second',
            slug='delete-me-second-confirm',
            description='Also should be deleted in bulk.',
            price_minor=12000,
            status=Product.Status.DRAFT,
        )
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/confirm/',
            {'action': 'delete-selected-products',
                'product_ids': f'{first.id},{second.id}'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Are you sure you want to delete 2 products?')

    def test_bulk_delete_confirmation_ignores_malformed_product_id_lists(self):
        product = Product.objects.create(
            category=self.category,
            name='Delete Me Safely',
            slug='delete-me-safely',
            description='Malformed IDs must not cause an admin error.',
            price_minor=11000,
            status=Product.Status.DRAFT,
        )
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/confirm/', {
            'action': 'delete-selected-products',
            'product_ids': [f"['{product.id}']"],
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        self.assertTrue(Product.objects.filter(pk=product.id).exists())

    def test_staff_products_use_confirmation_links_for_archive_and_delete(self):
        product = Product.objects.create(
            category=self.category,
            name='Archive Confirm Product',
            slug='archive-confirm-product',
            description='Should route through confirm flow.',
            price_minor=14000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/')

        self.assertContains(
            response,
            f'/admin/dashboard/confirm/?action=archive-product&product_id={product.id}',
        )
        self.assertContains(
            response,
            f'/admin/dashboard/confirm/?action=delete-product&product_id={product.id}',
        )

        confirm_response = self.client.post('/admin/dashboard/confirm/', {
            'action': 'delete-product',
            'product_id': str(product.id),
        })
        self.assertRedirects(confirm_response, '/admin/dashboard/products/')

    def test_products_page_shows_publish_action_only_for_draft_products(self):
        draft = Product.objects.create(
            category=self.category,
            name='Draft Publish Product',
            slug='draft-publish-product',
            description='Should offer a publish action.',
            price_minor=15000,
            status=Product.Status.DRAFT,
        )
        live = Product.objects.create(
            category=self.category,
            name='Live Publish Product',
            slug='live-publish-product',
            description='Already published.',
            price_minor=16000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/products/')

        self.assertContains(
            response,
            f'/admin/dashboard/confirm/?action=publish-product&product_id={draft.id}',
        )
        self.assertNotContains(
            response,
            f'/admin/dashboard/confirm/?action=publish-product&product_id={live.id}',
        )
        self.assertContains(response, 'Publish selected')

    def test_staff_can_publish_draft_product_from_confirmation_flow(self):
        product = Product.objects.create(
            category=self.category,
            name='Publish Me',
            slug='publish-me',
            description='Draft that should go live.',
            price_minor=17000,
            status=Product.Status.DRAFT,
        )
        self.client.force_login(self.staff)

        confirm_page = self.client.get(
            '/admin/dashboard/confirm/',
            {'action': 'publish-product', 'product_id': str(product.id)},
        )

        self.assertEqual(confirm_page.status_code, 200)
        self.assertContains(
            confirm_page,
            f'Are you sure you want to publish product {product.name}?')

        response = self.client.post('/admin/dashboard/confirm/', {
            'action': 'publish-product',
            'product_id': str(product.id),
        })

        self.assertRedirects(response, '/admin/dashboard/products/')
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.ACTIVE)
        self.assertTrue(product.is_active)

    def test_staff_can_bulk_publish_selected_draft_products(self):
        first = Product.objects.create(
            category=self.category,
            name='Bulk Publish First',
            slug='bulk-publish-first',
            description='Should be published in bulk.',
            price_minor=11000,
            status=Product.Status.DRAFT,
        )
        second = Product.objects.create(
            category=self.category,
            name='Bulk Publish Second',
            slug='bulk-publish-second',
            description='Should be published in bulk.',
            price_minor=12000,
            status=Product.Status.DRAFT,
        )
        live = Product.objects.create(
            category=self.category,
            name='Bulk Publish Already Live',
            slug='bulk-publish-already-live',
            description='Already published.',
            price_minor=13000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        confirm_page = self.client.get(
            '/admin/dashboard/confirm/',
            {'action': 'publish-selected-products',
                'product_ids': f'{first.id},{second.id}'},
        )

        self.assertEqual(confirm_page.status_code, 200)
        self.assertContains(
            confirm_page, 'Are you sure you want to publish 2 products?')

        response = self.client.post(
            '/admin/dashboard/confirm/',
            {
                'action': 'publish-selected-products',
                'product_ids': [str(first.id), str(second.id), str(live.id)],
            },
            follow=True,
        )

        self.assertRedirects(response, '/admin/dashboard/products/')
        self.assertContains(response, '2 products published.')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Product.Status.ACTIVE)
        self.assertEqual(second.status, Product.Status.ACTIVE)
        self.assertTrue(first.is_active)
        self.assertTrue(second.is_active)

    def test_staff_edit_form_posts_to_confirmation_route(self):
        """Editing goes straight to the edit URL; /confirm/ stays reachable.

        product_form_page.html posts to /products/<id>/edit/ rather than through
        the dashboard-era confirmation step. The confirm endpoint still exists
        for destructive actions, so both halves are asserted here.
        """
        product = Product.objects.create(
            category=self.category,
            name='Edit Confirm Product',
            slug='edit-confirm-product',
            description='Should confirm before saving.',
            price_minor=13000,
            status=Product.Status.ACTIVE,
        )
        self.client.force_login(self.staff)

        response = self.client.get(
            f'/admin/dashboard/products/{product.id}/edit/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'action="/admin/dashboard/products/{product.id}/edit/"')

        confirm_response = self.client.post('/admin/dashboard/confirm/', {
            'action': 'update-product',
            'product_id': str(product.id),
            'name': 'Updated Confirm Product',
            'slug': 'updated-confirm-product',
            'category': str(self.category.id),
            'description': 'Updated description.',
            'price': '200.00',
            'status': 'ACTIVE',
        })
        self.assertRedirects(confirm_response, '/admin/dashboard/products/')

    def test_staff_can_adjust_variant_stock(self):
        product = Product.objects.create(
            category=self.category,
            name='Linen Top',
            slug='linen-top',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        variant = ProductVariant.objects.create(
            product=product, sku='LINEN-S', stock_quantity=2)
        self.client.force_login(self.staff)

        response = self.client.post('/admin/dashboard/', {
            'action': 'adjust-stock',
            'variant': str(variant.id),
            'delta': '3',
            'reason': 'restock',
        })

        self.assertRedirects(response, '/admin/dashboard/')
        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 5)

    def test_django_admin_accepts_empty_json_fields(self):
        self.client.force_login(self.staff)

        response = self.client.post('/admin/catalog/product/add/', {
            'category': str(self.category.id),
            'name': 'Admin Silk Dress',
            'slug': 'admin-silk-dress',
            'tagline': '',
            'description': 'A silk dress created through Django admin.',
            'details': '',
            'price_minor': '24500',
            'compare_at_price_minor': '',
            'image_url': '',
            'images': '',
            'status': Product.Status.ACTIVE,
            'is_featured': '',
            'is_new_arrival': '',
            'is_best_seller': '',
            # catalog.Product.stock_quantity has default=0 but not blank=True,
            # so the admin form treats it as required and re-renders on a miss.
            'stock_quantity': '0',
            '_save': 'Save',
            'variants-TOTAL_FORMS': '0',
            'variants-INITIAL_FORMS': '0',
            'variants-MIN_NUM_FORMS': '0',
            'variants-MAX_NUM_FORMS': '1000',
        })

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(slug='admin-silk-dress')
        self.assertEqual(product.images, [])


class PromotionDashboardCRUDTests(TestCase):
    def setUp(self):
        from promotions.models import Promotion

        self.staff = get_user_model().objects.create_superuser(
            username='promotion-crud-staff',
            password='test-password',
            email='promotion-crud@example.com',
        )
        enroll_staff(self.staff)
        self.client.force_login(self.staff)
        self.promotion = Promotion.objects.create(
            name='Weekend offer',
            promotion_type=Promotion.Type.PERCENTAGE,
            discount_percent=15,
            status=Promotion.Status.DRAFT,
        )

    def test_promotion_list_exposes_view_edit_and_delete_actions(self):
        response = self.client.get('/admin/dashboard/promotions/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'href="/admin/dashboard/promotions/{self.promotion.pk}/"')
        self.assertContains(
            response,
            f'href="/admin/dashboard/promotions/{self.promotion.pk}/edit/"')
        self.assertContains(
            response,
            f'href="/admin/dashboard/promotions/{self.promotion.pk}/delete/"')

    def test_promotion_detail_is_read_only_and_links_to_edit(self):
        response = self.client.get(
            f'/admin/dashboard/promotions/{self.promotion.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.promotion.name)
        self.assertContains(response, 'Offer')
        self.assertContains(
            response,
            f'href="/admin/dashboard/promotions/{self.promotion.pk}/edit/"')

    def test_promotion_delete_requires_post(self):
        delete_url = (
            f'/admin/dashboard/promotions/{self.promotion.pk}/delete/')
        confirmation = self.client.get(delete_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'Delete promotion')

        response = self.client.post(delete_url)

        self.assertRedirects(response, '/admin/dashboard/promotions/')
        self.assertFalse(
            type(self.promotion).objects.filter(pk=self.promotion.pk).exists())

    def test_promotion_with_redemptions_cannot_be_deleted(self):
        from cart.models import Cart
        from promotions.models import PromotionRedemption

        cart = Cart.objects.create(cart_key='promotion-redemption-cart')
        order = Order.objects.create(
            order_number='AT-PROMOTION-REDEMPTION-001',
            cart=cart,
            customer={'fullName': 'Promotion Buyer',
                      'email': 'promotion-buyer@example.com'},
            subtotal_minor=1000,
            total_minor=1000,
            shipping_cost_minor=0,
            payment_method='mpesa',
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        PromotionRedemption.objects.create(
            promotion=self.promotion,
            order=order,
            discount_minor=100,
        )

        response = self.client.post(
            f'/admin/dashboard/promotions/{self.promotion.pk}/delete/',
            follow=True,
        )

        self.assertRedirects(response, '/admin/dashboard/promotions/')
        self.assertTrue(
            type(self.promotion).objects.filter(pk=self.promotion.pk).exists())
        self.assertContains(response, 'cannot be deleted')


class AdminAuthTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username='root-admin', password='root-pass-123', email='root@example.com')
        staff = User.objects.create_user(
            username='plain-staff', password='staff-pass-123', email='staff@example.com')
        staff.is_staff = True
        staff.save()
        enroll_staff(staff)
        self.staff = staff
        self.customer = User.objects.create_user(
            username='regular-user', password='user-pass-123', email='user@example.com')

    def test_landing_page_accessible_anonymously(self):
        response = self.client.get('/admin/dashboard/landing/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administration Portal')

    def test_landing_page_links_to_django_admin_site(self):
        response = self.client.get('/admin/dashboard/landing/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/admin/"')

    def test_login_page_renders(self):
        response = self.client.get('/admin/dashboard/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign In')

    def test_staff_can_login_via_custom_form(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'plain-staff',
            'password': 'staff-pass-123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.staff.id)

    def test_login_honours_next_parameter(self):
        response = self.client.post(
            '/admin/dashboard/login/?next=/admin/dashboard/products/', {
                'username': 'plain-staff',
                'password': 'staff-pass-123',
            })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/products/')

    def test_non_staff_cannot_login(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'regular-user',
            'password': 'user-pass-123',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'does not have admin access')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_staff_can_login_via_email(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'staff@example.com',
            'password': 'staff-pass-123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.staff.id)

    def test_staff_can_login_via_email_ignoring_case(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'STAFF@Example.COM',
            'password': 'staff-pass-123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.staff.id)

    def test_staff_can_login_via_email_when_customer_mirror_exists(self):
        User = get_user_model()
        User.objects.create_user(
            username='supabase_mirror_login', password='mirror-pass-123',
            email='staff@example.com')

        response = self.client.post('/admin/dashboard/login/', {
            'username': 'staff@example.com',
            'password': 'staff-pass-123',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.staff.id)

    def test_email_login_rejects_wrong_password(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'staff@example.com',
            'password': 'wrong-password',
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_email_login_rejects_non_staff(self):
        response = self.client.post('/admin/dashboard/login/', {
            'username': 'user@example.com',
            'password': 'user-pass-123',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'does not have admin access')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_view_redirects_authenticated_staff(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/login/')

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/')

    def test_register_page_requires_superuser(self):
        response = self.client.get('/admin/dashboard/register/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)

        self.client.force_login(self.staff)
        response = self.client.get('/admin/dashboard/register/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)

    def test_login_page_does_not_offer_public_admin_registration(self):
        response = self.client.get('/admin/dashboard/login/')

        self.assertNotContains(response, '/admin/dashboard/register/')
        self.assertContains(response, 'created by a superuser')

    def test_anonymous_signup_is_rejected_without_creating_account(self):
        response = self.client.post('/admin/dashboard/register/', {
            'username': 'public-admin',
            'email': 'public@example.com',
            'first_name': 'Public',
            'last_name': 'Admin',
            'is_active': 'on',
            'password': 'Pub!ic-2024',
            'password_confirm': 'Pub!ic-2024',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)
        self.assertFalse(get_user_model().objects.filter(
            username='public-admin').exists())

    def test_anonymous_superuser_signup_is_rejected(self):
        response = self.client.post('/admin/dashboard/register/', {
            'username': 'public-super',
            'email': 'public-super@example.com',
            'is_active': 'on',
            'is_superuser': 'on',
            'password': 'Pub!ic-2024',
            'password_confirm': 'Pub!ic-2024',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(get_user_model().objects.filter(
            username='public-super').exists())

    def test_invite_page_requires_superuser(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/admin-users/invite/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)

    def test_superuser_can_open_register_page(self):
        self.client.force_login(self.superuser)

        response = self.client.get('/admin/dashboard/register/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create administrator account')

    def test_superuser_can_create_admin_account_with_powers(self):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name='Inventory Managers')
        self.client.force_login(self.superuser)

        response = self.client.post('/admin/dashboard/register/', {
            'username': 'new-admin',
            'email': 'new-admin@example.com',
            'first_name': 'New',
            'last_name': 'Admin',
            'groups': [str(group.id)],
            'is_superuser': 'on',
            'is_active': 'on',
            'password': 'Adm1n-S3cret!',
            'password_confirm': 'Adm1n-S3cret!',
        })

        self.assertRedirects(response, '/admin/dashboard/admin-users/')
        user = get_user_model().objects.get(username='new-admin')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('Adm1n-S3cret!'))
        self.assertIn(group, user.groups.all())
        self.assertTrue(StaffProfile.objects.filter(user=user).exists())
        self.assertTrue(AdminNotification.objects.filter(
            recipient=user,
            title='New admin account created',
        ).exists())

    def test_superuser_can_create_staff_via_invite_page(self):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name='Catalog Managers')
        self.client.force_login(self.superuser)

        response = self.client.post('/admin/dashboard/admin-users/invite/', {
            'username': 'invited-admin',
            'email': 'invited@example.com',
            'first_name': 'Invited',
            'last_name': 'Admin',
            'groups': [str(group.id)],
            'is_active': 'on',
            'password': 'Inv!ted-2024',
            'password_confirm': 'Inv!ted-2024',
        })

        self.assertRedirects(response, '/admin/dashboard/admin-users/')
        user = get_user_model().objects.get(username='invited-admin')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIn(group, user.groups.all())
        self.assertTrue(StaffProfile.objects.filter(user=user).exists())

    def test_signup_rejects_mismatched_passwords(self):
        self.client.force_login(self.superuser)

        response = self.client.post('/admin/dashboard/register/', {
            'username': 'mismatch-admin',
            'email': 'mismatch@example.com',
            'is_active': 'on',
            'password': 'Adm1n-S3cret!',
            'password_confirm': 'Different-123!',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(
            username='mismatch-admin').exists())

    def test_logout_via_custom_view_signs_out_and_redirects_to_landing(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/logout/')

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/admin/dashboard/landing/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dashboard_sign_out_link_targets_custom_logout_view(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/')

        self.assertContains(response, '/admin/dashboard/logout/')
        self.assertNotContains(response, 'href="/admin/logout/"')


class AdminUsersGridTests(TestCase):
    """Admin Users page: row action links, name links and real role labels."""

    def setUp(self):
        from access_control.models import Role

        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username='grid-root', password='root-pass-123',
            email='grid-root@example.com')
        viewer = User.objects.create_user(
            username='grid-viewer', password='staff-pass-123',
            email='grid-viewer@example.com')
        viewer.is_staff = True
        viewer.save()
        enroll_staff(viewer, codes=['staff.view'])
        self.viewer = viewer

        target = User.objects.create_user(
            username='grid-target', password='staff-pass-123',
            email='grid-target@example.com')
        target.first_name = 'Target'
        target.last_name = 'Person'
        target.is_staff = True
        target.save()
        profile = StaffProfile.objects.create(user=target)
        profile.roles.add(Role.objects.create(
            slug='grid-fixture-role', name='Grid Fixture Role'))
        self.target = target

    def test_rows_link_to_staff_detail_and_edit_pages(self):
        self.client.force_login(self.superuser)

        response = self.client.get('/admin/dashboard/admin-users/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'href="/admin/dashboard/staff/{self.target.pk}/"')
        self.assertContains(
            response, f'href="/admin/dashboard/staff/{self.target.pk}/edit/"')

    def test_role_column_shows_assigned_roles(self):
        self.client.force_login(self.superuser)

        response = self.client.get('/admin/dashboard/admin-users/')

        self.assertContains(response, 'Grid Fixture Role')
        self.assertContains(response, 'Super Admin')
        self.assertContains(response, 'No roles yet')

    def test_assign_link_hidden_without_staff_update_permission(self):
        self.client.force_login(self.viewer)

        response = self.client.get('/admin/dashboard/admin-users/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'href="/admin/dashboard/staff/{self.target.pk}/"')
        self.assertNotContains(
            response, f'/admin/dashboard/staff/{self.target.pk}/edit/')


class ActivityCenterTests(TestCase):
    """Tests for the Activity & Logs center, security/error/health pages and
    the audit activity sections wired into the detail pages."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username='root-admin', password='root-pass-123', email='root@example.com')
        staff = User.objects.create_user(
            username='plain-staff', password='staff-pass-123', email='staff@example.com')
        staff.is_staff = True
        staff.save()
        enroll_staff(staff)
        self.staff = staff
        self.customer = User.objects.create_user(
            username='regular-user', password='user-pass-123', email='user@example.com')

    def log(self, action, **kwargs):
        kwargs.setdefault('actor', self.staff)
        kwargs.setdefault('actor_role', 'staff')
        kwargs.setdefault('actor_email', self.staff.email)
        kwargs.setdefault('object_repr', 'Test log entry')
        kwargs.setdefault('result', AuditLog.Result.SUCCESS)
        kwargs.setdefault('severity', AuditLog.Severity.INFO)
        return AuditLog.objects.create(action=action, **kwargs)

    # -- access control ----------------------------------------------------

    def test_activity_page_redirects_anonymous_to_admin_login(self):
        response = self.client.get('/admin/dashboard/activity/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/dashboard/login/', response.url)

    def test_activity_page_denies_authenticated_non_staff_with_403(self):
        self.client.force_login(self.customer)

        response = self.client.get('/admin/dashboard/activity/')

        self.assertContains(response, 'Access Denied', status_code=403)

    def test_security_and_health_pages_deny_non_staff_with_403(self):
        self.client.force_login(self.customer)

        response = self.client.get('/admin/dashboard/security/')
        self.assertEqual(response.status_code, 403)
        response = self.client.get('/admin/dashboard/system-health/')
        self.assertEqual(response.status_code, 403)

    # -- overview ----------------------------------------------------------

    def test_activity_page_renders_for_staff(self):
        self.log('login', object_repr='Welcome back, staff')
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/activity/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Activity &amp; Logs')
        self.assertContains(response, 'Total events')
        self.assertContains(response, 'Welcome back, staff')

    def test_legacy_audit_logs_alias_renders_activity_overview(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/audit-logs/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Activity &amp; Logs')

    def test_activity_page_applies_action_filter(self):
        self.log('login', object_repr='Login entry')
        self.log('security_event', object_repr='Suspicious probe',
                 severity=AuditLog.Severity.HIGH)
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/?action=login')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Login entry')
        self.assertNotContains(response, 'Suspicious probe')

    def test_activity_page_table_view_mode(self):
        self.log('login')
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/activity/?view=table')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'table-container')

    def test_activity_page_empty_state(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/activity/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No activity')

    # -- export ------------------------------------------------------------

    def test_activity_export_csv_matches_filtered_logs(self):
        self.log('login', object_repr='CSV exportable login')
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/export/?format=csv')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'], 'text/csv')
        self.assertContains(response, 'time_utc,action,category,severity')
        self.assertContains(response, 'CSV exportable login')

    def test_activity_export_json_matches_filtered_logs(self):
        self.log('login', object_repr='JSON exportable login')
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/export/?format=json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'], 'application/json')
        self.assertContains(response, '"action": "login"')
        self.assertContains(response, 'JSON exportable login')

    def test_activity_export_rejects_unknown_format(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/export/?format=xml')

        self.assertEqual(response.status_code, 400)

    # -- request trace, security, errors, health ---------------------------

    def test_request_trace_page_renders_request_timeline(self):
        self.log('checkout_started', request_id='req_trace123456',
                 path='/api/cart/checkout')
        self.log('payment_success', request_id='req_trace123456',
                 path='/api/payments/mpesa')
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/request/req_trace123456/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request Trace')
        self.assertContains(response, 'req_trace123456')
        self.assertContains(response, '2 events')

    def test_request_trace_unknown_request_id_renders_empty_state(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            '/admin/dashboard/activity/request/req_no_such_request/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request Trace')
        self.assertContains(response, 'No activity')

    def test_security_center_renders_security_events(self):
        self.log('login_failed', object_repr='Brute force attempt',
                 result=AuditLog.Result.FAILURE, severity=AuditLog.Severity.HIGH)
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/security/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Security Center')
        self.assertContains(response, 'Brute force attempt')

    def test_error_center_renders_failed_events(self):
        self.log('server_error', object_repr='Database outage',
                 result=AuditLog.Result.FAILURE, severity=AuditLog.Severity.CRITICAL)
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/activity/errors/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Error Center')
        self.assertContains(response, 'Database outage')

    def test_system_health_renders_honest_checks(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/system-health/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Health')
        self.assertContains(response, 'Database')

    # -- customer / product / order detail activity -----------------------

    def test_customer_detail_renders_account_activity(self):
        self.log('login', object_repr='Customer login', actor=self.customer,
                 object_type='user', object_id=str(self.customer.pk))
        self.client.force_login(self.staff)

        response = self.client.get(
            f'/admin/dashboard/customers/{self.customer.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'regular-user')
        self.assertContains(response, 'Customer login')

    def test_customer_detail_redirects_when_customer_missing(self):
        self.client.force_login(self.staff)

        response = self.client.get('/admin/dashboard/customers/99999/')

        self.assertRedirects(response, '/admin/dashboard/customers/')

    def test_product_detail_page_renders_product_activity(self):
        product = Product.objects.create(
            category=Category.objects.create(name='Dresses', slug='dresses'),
            name='Linen Top', slug='linen-top',
            description='A breathable linen top.', price_minor=12000,
            status=Product.Status.ACTIVE,
        )
        self.log('update', object_repr=f'Product {product.name}',
                 object_type='product', object_id=str(product.id))
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/products/{product.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product activity')
        self.assertContains(response, 'Product Linen Top')

    def test_order_detail_page_renders_order_activity(self):
        from cart.models import Cart

        cart = Cart.objects.create(cart_key='activity-order-cart')
        order = Order.objects.create(
            order_number='AT-ACT-001', cart=cart,
            customer={'fullName': 'Activity Buyer',
                      'email': 'buyer@example.com'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PROCESSING,
        )
        self.log('status_change', object_repr=f'Order {order.order_number}',
                 object_type='order', object_id=str(order.pk))
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/orders/{order.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order activity')
        self.assertContains(response, 'Order AT-ACT-001')

    def test_order_detail_page_renders_receipt_panel(self):
        from cart.models import Cart
        from receipts.models import Receipt

        cart = Cart.objects.create(cart_key='receipt-order-cart')
        order = Order.objects.create(
            order_number='AT-RCP-001', cart=cart,
            customer={'fullName': 'Receipt Buyer', 'email': 'r@example.com'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000999',
            amount_minor=1450, currency='KES',
            gateway_reference='GTW-001', status=Receipt.Status.GENERATED,
            payload_size=123,
        )
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/orders/{order.pk}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Official receipt')
        self.assertContains(response, 'RCP-2030-000999')
        self.assertContains(
            response, f'/admin/dashboard/orders/{order.pk}/receipt/download/')
        self.assertContains(
            response, f'/admin/dashboard/orders/{order.pk}/receipt/regenerate/')

    def test_order_detail_page_shows_regenerate_for_failed_receipt(self):
        from cart.models import Cart
        from receipts.models import Receipt

        cart = Cart.objects.create(cart_key='failed-receipt-cart')
        order = Order.objects.create(
            order_number='AT-RCP-FAIL', cart=cart,
            customer={'fullName': 'Fail Buyer', 'email': 'f@example.com'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000988',
            amount_minor=1450, currency='KES',
            status=Receipt.Status.FAILED, notes='Failed at render',
        )
        self.client.force_login(self.staff)

        response = self.client.get(f'/admin/dashboard/orders/{order.pk}/')

        self.assertEqual(response.status_code, 200)
        url = f'/admin/dashboard/orders/{order.pk}/receipt/regenerate/'
        self.assertContains(response, url)

    def test_admin_can_download_receipt_pdf(self):
        from cart.models import Cart
        from receipts.models import Receipt
        from unittest.mock import patch

        cart = Cart.objects.create(cart_key='dl-receipt-cart')
        order = Order.objects.create(
            order_number='AT-RCP-DL', cart=cart,
            customer={'fullName': 'DL Buyer'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000977',
            amount_minor=1450, currency='KES', status=Receipt.Status.GENERATED,
            pdf_key='receipts/AT-RCP-DL/RCP-2030-000977.pdf',
        )
        self.client.force_login(self.staff)

        with patch('admin_ui.views.read_pdf_bytes',
                   return_value=b'%PDF-1.4 test receipt'):
            response = self.client.get(
                f'/admin/dashboard/orders/{order.pk}/receipt/download/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(
            b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_admin_can_regenerate_failed_receipt(self):
        import tempfile

        from django.test import override_settings
        from cart.models import Cart
        from receipts.models import Receipt

        cart = Cart.objects.create(cart_key='reg-receipt-cart')
        order = Order.objects.create(
            order_number='AT-RCP-REG', cart=cart,
            customer={'fullName': 'Reg Buyer', 'email': 're@example.com'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        receipt = Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000966',
            amount_minor=1450, currency='KES',
            status=Receipt.Status.FAILED, notes='Failed at render',
        )
        self.client.force_login(self.staff)

        media = tempfile.mkdtemp(prefix='modeza-admin-receipt-')
        with override_settings(STORAGES={
                'default': {
                    'BACKEND': 'django.core.files.storage.FileSystemStorage',
                    'OPTIONS': {'location': media},
                },
                'staticfiles': {
                    'BACKEND': (
                        'whitenoise.storage.'
                        'CompressedManifestStaticFilesStorage'),
                },
        }):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    f'/admin/dashboard/orders/{order.pk}/receipt/regenerate/')

        self.assertRedirects(
            response, f'/admin/dashboard/orders/{order.pk}/')
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, Receipt.Status.GENERATED)
        self.assertTrue(receipt.pdf_key)
        self.assertGreater(receipt.payload_size, 0)
        self.assertTrue(
            AuditLog.objects.filter(
                action='receipt_regenerated',
                object_id=str(receipt.pk)).exists())

    def test_receipt_actions_require_staff_session(self):
        from cart.models import Cart
        from receipts.models import Receipt

        cart = Cart.objects.create(cart_key='anon-receipt-cart')
        order = Order.objects.create(
            order_number='AT-RCP-ANON', cart=cart,
            customer={'fullName': 'Anon Buyer'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000955',
            amount_minor=1450, currency='KES', status=Receipt.Status.GENERATED,
            pdf_key='receipts/AT-RCP-ANON/RCP-2030-000955.pdf',
        )

        for url in (
                f'/admin/dashboard/orders/{order.pk}/receipt/download/',
                f'/admin/dashboard/orders/{order.pk}/receipt/regenerate/'):
            response = self.client.get(url)
            self.assertIn(f'/admin/dashboard/login/?next={url}',
                          response.get('Location', ''))

    def test_customer_session_cannot_download_receipt(self):
        from cart.models import Cart
        from receipts.models import Receipt

        cart = Cart.objects.create(cart_key='cust-receipt-cart')
        order = Order.objects.create(
            order_number='AT-RCP-CUST', cart=cart,
            customer={'fullName': 'Cust Buyer'},
            subtotal_minor=1200, total_minor=1450, shipping_cost_minor=250,
            payment_method='mpesa', payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.CONFIRMED,
        )
        Receipt.objects.create(
            order=order, receipt_number='RCP-2030-000944',
            amount_minor=1450, currency='KES', status=Receipt.Status.GENERATED,
            pdf_key='receipts/AT-RCP-CUST/RCP-2030-000944.pdf',
        )
        self.client.force_login(self.customer)

        response = self.client.get(
            f'/admin/dashboard/orders/{order.pk}/receipt/download/')

        # Authenticated customers with no staff permissions are denied
        # fail-closed with 403 (anonymous users still get the login redirect).
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Access Denied', status_code=403)
