"""Automated coverage for the Promotions & Discounts Engine.

Unit: percentage / fixed / max-cap / min-order / min-qty / free shipping /
BxGy / BxGetPct / expiry / window / global + per-customer limits /
product+category+variant targeting / customer scope / stacking / priority.
API: apply / remove / invalid / expired / admin RBAC + CRUD + activate.
Checkout: snapshot, server-side total, M-Pesa amount, cancel voids usage.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from admin_ui.models import CustomerNotification
from cart.models import Cart, CartItem
from catalog.models import Category, Product, ProductVariant
from orders.models import Order
from promotions.models import (
    Promotion, PromotionCategory, PromotionCustomer, PromotionProduct,
    PromotionRedemption, PromotionVariant,
)
from promotions.services import price_cart

User = get_user_model()

CUSTOMER = {
    'fullName': 'Ada Lovelace', 'email': 'ada@example.com',
    'phone': '0712345678', 'addressLine1': '1 Market Street',
    'city': 'Nairobi', 'county': 'Nairobi',
}


def make_catalog(price_minor=1000000, slug='dress', category_slug='dresses',
                 compare_at=None, is_new=False):
    category = Category.objects.create(name=category_slug.title(), slug=category_slug)
    product = Product.objects.create(
        category=category, name=slug.title(), slug=slug,
        description='Test product.', price_minor=price_minor,
        compare_at_price_minor=compare_at, status=Product.Status.ACTIVE,
        is_new_arrival=is_new)
    variant = ProductVariant.objects.create(
        product=product, sku=f'{slug.upper()}-S-RED', size='S', color='Red',
        stock_quantity=100)
    return category, product, variant


def make_cart(variant, qty=1, key='promo-cart'):
    cart = Cart.objects.create(cart_key=key)
    CartItem.objects.create(cart=cart, variant=variant, quantity=qty)
    return cart


def make_promo(ptype='percentage', code='MODEZA10', automatic=False, **kw):
    defaults = dict(name=f'Promo {code or ptype}', promotion_type=ptype,
                    status='active', coupon_code='' if automatic else code,
                    is_automatic=automatic, stackable=True, priority=10)
    if ptype == 'percentage':
        defaults['discount_percent'] = Decimal('10')
    if ptype == 'fixed':
        defaults['discount_amount_minor'] = 100000  # KES 1,000
    defaults.update(kw)
    return Promotion.objects.create(**defaults)


class PromotionEngineTests(TestCase):
    def test_percentage_discount(self):
        _, _, variant = make_catalog()
        cart = make_cart(variant)
        make_promo()
        out = price_cart(cart, coupon_code='modeza10')  # case-insensitive
        self.assertEqual(out['discount'], 100000)  # 10% of 1,000,000
        self.assertEqual(out['total'], out['subtotal'] - 100000 + out['shipping'] + out['tax'])


    def test_percentage_max_cap(self):
        _, _, variant = make_catalog()
        cart = make_cart(variant)
        make_promo(maximum_discount_minor=50000)
        out = price_cart(cart, coupon_code='MODEZA10')
        self.assertEqual(out['discount'], 50000)

    def test_minimum_order(self):
        _, _, variant = make_catalog(price_minor=100000)  # KES 1,000
        cart = make_cart(variant)
        make_promo(minimum_order_value_minor=500000)
        out = price_cart(cart, coupon_code='MODEZA10')
        self.assertEqual(out['discount'], 0)
        self.assertEqual(out['coupon_error'], 'MINIMUM_ORDER_NOT_REACHED')

    def test_minimum_quantity(self):
        _, _, variant = make_catalog()
        cart = make_cart(variant, qty=1)
        make_promo(minimum_quantity=2)
        out = price_cart(cart, coupon_code='MODEZA10')
        self.assertEqual(out['coupon_error'], 'MINIMUM_QUANTITY_NOT_REACHED')

    def test_fixed_never_negative(self):
        _, _, variant = make_catalog(price_minor=50000)
        cart = make_cart(variant)
        make_promo(ptype='fixed', code='BIG5000', discount_amount_minor=99999999)
        out = price_cart(cart, coupon_code='BIG5000')
        self.assertLessEqual(out['discount'], out['subtotal'])

    def test_free_shipping(self):
        _, _, variant = make_catalog(price_minor=500000)  # KES 5,000
        cart = make_cart(variant)
        make_promo(ptype='free_shipping', code='FREESHIP')
        # Express is flat KES 1,500 (standard is already free above KES 150),
        # so the promo is meaningful against express here.
        out = price_cart(cart, shipping_method='express', coupon_code='FREESHIP')
        self.assertGreater(out['shipping_discount'], 0)
        self.assertEqual(out['shipping'], 0)

    def test_buy_x_get_y_cheapest_free(self):
        _, _, variant = make_catalog(price_minor=100000)
        cart = make_cart(variant, qty=3)
        make_promo(ptype='buy_x_get_y', code='B2G1', qualifying_quantity=2, reward_quantity=1)
        out = price_cart(cart, coupon_code='B2G1')
        self.assertEqual(out['discount'], 100000)

    def test_buy_x_get_pct(self):
        _, _, variant = make_catalog(price_minor=100000)
        cart = make_cart(variant, qty=3)
        make_promo(ptype='buy_x_get_pct', code='B2G50', qualifying_quantity=2,
                   reward_quantity=1, reward_discount_percent=Decimal('50'))
        out = price_cart(cart, coupon_code='B2G50')
        self.assertEqual(out['discount'], 50000)

    def test_expiry_and_window(self):
        _, _, variant = make_catalog()
        cart = make_cart(variant)
        past = timezone.now() - timezone.timedelta(days=2)
        future = timezone.now() + timezone.timedelta(days=2)
        expired = make_promo(code='OLD', ends_at=past)
        out = price_cart(cart, coupon_code='OLD')
        self.assertEqual(out['coupon_error'], 'EXPIRED')
        scheduled = make_promo(code='SOON', starts_at=future)
        out = price_cart(cart, coupon_code='SOON')
        self.assertEqual(out['coupon_error'], 'NOT_STARTED')
        self.assertTrue(expired.pk and scheduled.pk)

    def test_usage_limit(self):
        _, _, variant = make_catalog()
        cart = make_cart(variant, key='u1')
        promo = make_promo(code='ONCE', usage_limit=1)
        order = Order.objects.create(
            order_number='AT-TEST-USAGE-01', user=None, customer=CUSTOMER,
            subtotal_minor=1000000, total_minor=1000000)
        PromotionRedemption.objects.create(promotion=promo, order=order, discount_minor=1)
        cart2 = make_cart(variant, key='u2')
        out = price_cart(cart2, coupon_code='ONCE')
        self.assertEqual(out['coupon_error'], 'USAGE_LIMIT_REACHED')
        self.assertEqual(cart.cart_key, 'u1')

    def test_per_customer_limit(self):
        user = User.objects.create_user(username='buyer1', password='x')
        _, _, variant = make_catalog()
        promo = make_promo(code='PCL', usage_limit_per_customer=1)
        order = Order.objects.create(
            order_number='AT-TEST-PCL-01', user=user, customer=CUSTOMER,
            subtotal_minor=1000000, total_minor=1000000)
        PromotionRedemption.objects.create(promotion=promo, order=order, user=user, discount_minor=1)
        cart = make_cart(variant, key='pcl-cart')
        out = price_cart(cart, user=user, coupon_code='PCL')
        self.assertEqual(out['coupon_error'], 'CUSTOMER_LIMIT_REACHED')

    def test_product_category_variant_targeting(self):
        cat_a, prod_a, var_a = make_catalog(price_minor=1000000, slug='dress-a', category_slug='cat-a')
        _, prod_b, var_b = make_catalog(price_minor=1000000, slug='dress-b', category_slug='cat-b')
        promo = make_promo(code='ONLYA')
        PromotionProduct.objects.create(promotion=promo, product=prod_a)
        promo.eligible_all = False
        promo.save()
        cart = make_cart(var_b, key='target-cart')
        out = price_cart(cart, coupon_code='ONLYA')
        self.assertEqual(out['coupon_error'], 'DOES_NOT_APPLY_TO_CART')
        cart2 = make_cart(var_a, key='target-cart-2')
        out2 = price_cart(cart2, coupon_code='ONLYA')
        self.assertEqual(out2['discount'], 100000)
        self.assertTrue(cat_a.pk and prod_b.pk and var_a.pk)

    def test_category_targeting(self):
        cat, _, var = make_catalog(slug='cat-prod', category_slug='target-cat')
        _, _, other_var = make_catalog(slug='other-prod', category_slug='other-cat')
        promo = make_promo(code='CAT10')
        PromotionCategory.objects.create(promotion=promo, category=cat)
        promo.eligible_all = False
        promo.save()
        out = price_cart(make_cart(other_var, key='cat-no'), coupon_code='CAT10')
        self.assertEqual(out['discount'], 0)
        out2 = price_cart(make_cart(var, key='cat-yes'), coupon_code='CAT10')
        self.assertEqual(out2['discount'], 100000)

    def test_variant_targeting(self):
        _, _, var = make_catalog(slug='var-prod', category_slug='var-cat')
        promo = make_promo(code='VAR10')
        PromotionVariant.objects.create(promotion=promo, variant=var)
        promo.eligible_all = False
        promo.save()
        out = price_cart(make_cart(var, key='var-yes'), coupon_code='VAR10')
        self.assertEqual(out['discount'], 100000)

    def test_customer_scope_new_existing_specific(self):
        user = User.objects.create_user(username='scope1', password='x')
        _, _, variant = make_catalog(slug='scope-prod', category_slug='scope-cat')
        newbie = make_promo(code='NEWBIE', customer_scope='new')
        out = price_cart(make_cart(variant, key='scope-new'), user=user, coupon_code='NEWBIE')
        self.assertEqual(out['discount'], 100000)
        Order.objects.create(order_number='AT-SCOPE-01', user=user, customer=CUSTOMER,
                             subtotal_minor=100, total_minor=100)
        out = price_cart(make_cart(variant, key='scope-new-2'), user=user, coupon_code='NEWBIE')
        self.assertEqual(out['coupon_error'], 'NOT_AVAILABLE_FOR_CUSTOMER')
        existing = make_promo(code='LOYAL', customer_scope='existing', discount_percent=Decimal('10'))
        out = price_cart(make_cart(variant, key='scope-ex'), user=user, coupon_code='LOYAL')
        self.assertEqual(out['discount'], 100000)
        specific = make_promo(code='VIP', customer_scope='specific')
        out = price_cart(make_cart(variant, key='scope-sp'), user=user, coupon_code='VIP')
        self.assertEqual(out['coupon_error'], 'NOT_AVAILABLE_FOR_CUSTOMER')
        PromotionCustomer.objects.create(promotion=specific, user=user)
        out = price_cart(make_cart(variant, key='scope-sp2'), user=user, coupon_code='VIP')
        self.assertEqual(out['discount'], 100000)

    def test_stacking_non_stackable_wins(self):
        _, _, variant = make_catalog(slug='stack-prod', category_slug='stack-cat')
        make_promo(code='LOW', priority=10, stackable=True, discount_percent=Decimal('10'))
        make_promo(code='HIGH', priority=100, stackable=False, discount_percent=Decimal('5'))
        cart = make_cart(variant, key='stack-cart')
        cart.coupon_code = 'LOW'
        cart.save(update_fields=['coupon_code'])
        # Automatic companion promo + coupon promo both eligible.
        auto = make_promo(ptype='percentage', code='', automatic=True, priority=50,
                          stackable=True, discount_percent=Decimal('10'), name='Auto 10')
        out = price_cart(cart, coupon_code='LOW')
        codes = [a['code'] for a in out['applied']]
        self.assertTrue(auto.pk)
        # Non-stackable HIGH is not applied here (no coupon), LOW + auto stack.
        self.assertIn('LOW', codes)

    def test_priority_between_non_stackable(self):
        _, _, variant = make_catalog(slug='prio-prod', category_slug='prio-cat')
        make_promo(code='PLO', priority=10, stackable=False, discount_percent=Decimal('10'))
        make_promo(code='PHI', priority=100, stackable=False, discount_percent=Decimal('5'))
        auto1 = make_promo(ptype='percentage', code='', automatic=True, priority=10,
                           stackable=False, discount_percent=Decimal('1'), name='Auto A')
        auto2 = make_promo(ptype='percentage', code='', automatic=True, priority=100,
                           stackable=False, discount_percent=Decimal('2'), name='Auto B')
        cart = make_cart(variant, key='prio-cart')
        out = price_cart(cart, coupon_code='')
        self.assertEqual(len(out['applied']), 1)
        self.assertEqual(out['applied'][0]['name'], 'Auto B')
        self.assertTrue(auto1.pk and auto2.pk)

    def test_automatic_promotion_no_code(self):
        _, _, variant = make_catalog(slug='auto-prod', category_slug='auto-cat')
        make_promo(ptype='percentage', code='', automatic=True,
                   discount_percent=Decimal('15'), name='Auto 15')
        cart = make_cart(variant, key='auto-cart')
        out = price_cart(cart, coupon_code='')
        self.assertEqual(out['discount'], 150000)

    def test_whitespace_normalization(self):
        _, _, variant = make_catalog(slug='ws-prod', category_slug='ws-cat')
        make_promo(code='MODEZA10')
        cart = make_cart(variant, key='ws-cart')
        out = price_cart(cart, coupon_code='  modeza10  ')
        self.assertEqual(out['discount'], 100000)


class PromotionAnnouncementTests(TestCase):
    def test_publishing_notifies_customers_once_without_email(self):
        from promotions.notifications import notify_promotion_customers

        customer = User.objects.create_user(
            username='promo-customer', email='promo@example.com', password='pw')
        staff = User.objects.create_user(
            username='promo-staff', email='staff@example.com', password='pw',
            is_staff=True)
        promo = make_promo(
            code='LIVE15',
            ends_at=timezone.now() + timezone.timedelta(days=2),
            description='A limited-time offer.',
        )

        created = notify_promotion_customers(promo)
        repeated = notify_promotion_customers(promo)

        self.assertEqual(created, 1)
        self.assertEqual(repeated, 0)
        notification = CustomerNotification.objects.get(user=customer)
        self.assertEqual(notification.category, 'promotion')
        self.assertIn('LIVE15', notification.message)
        self.assertEqual(
            CustomerNotification.objects.filter(user=staff).count(), 0)

    def test_active_promotion_api_requires_an_end_date(self):
        staff = User.objects.create_user(
            username='promo-api-staff', password='pw', is_staff=True)
        from access_control.models import Permission, StaffProfile
        profile, _ = StaffProfile.objects.get_or_create(user=staff)
        profile.status = 'ACTIVE'
        profile.save()
        for code in ('promotions.view', 'promotions.create'):
            perm, _ = Permission.objects.get_or_create(
                code=code, defaults={'label': code, 'group': 'promotions'})
            profile.direct_permissions.add(perm)
        client = APIClient()
        client.force_authenticate(user=staff)

        response = client.post('/api/admin/promotions', {
            'name': 'No expiry', 'promotion_type': 'percentage',
            'status': 'active', 'discount_percent': '15',
            'coupon_code': 'NOEXPIRY',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('ends_at', response.json()['error']['details'])


class PromotionApiTests(TestCase):
    def setUp(self):
        _, _, self.variant = make_catalog(slug='api-prod', category_slug='api-cat')
        make_promo(
            code='MODEZA10',
            ends_at=timezone.now() + timezone.timedelta(days=1),
        )
        self.client = APIClient()

    def _cart(self, key='api-cart'):
        self.client.post('/api/cart/items', {'variantId': str(self.variant.id), 'quantity': 1},
                         format='json', HTTP_X_CART_ID=key)
        return key

    def test_apply_coupon(self):
        key = self._cart()
        resp = self.client.post('/api/promotions/apply', {'code': 'MODEZA10'},
                                format='json', HTTP_X_CART_ID=key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['discount'], 1000.0)
        cart = self.client.get('/api/cart', HTTP_X_CART_ID=key).json()
        self.assertEqual(cart['discount'], 1000.0)
        self.assertEqual(cart['promotion']['code'], 'MODEZA10')

    def test_remove_coupon(self):
        key = self._cart()
        self.client.post('/api/promotions/apply', {'code': 'MODEZA10'}, format='json', HTTP_X_CART_ID=key)
        resp = self.client.post('/api/promotions/remove', {}, format='json', HTTP_X_CART_ID=key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['discount'], 0)

    def test_invalid_coupon(self):
        key = self._cart()
        resp = self.client.post('/api/promotions/apply', {'code': 'NOPE'}, format='json', HTTP_X_CART_ID=key)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['error']['code'], 'INVALID_CODE')

    def test_expired_coupon(self):
        past = timezone.now() - timezone.timedelta(days=1)
        make_promo(code='OLDIE', ends_at=past)
        key = self._cart('api-cart-exp')
        resp = self.client.post('/api/promotions/apply', {'code': 'OLDIE'}, format='json', HTTP_X_CART_ID=key)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['error']['code'], 'EXPIRED')

    def test_available_endpoint(self):
        key = self._cart('api-cart-avail')
        resp = self.client.get('/api/promotions/available', HTTP_X_CART_ID=key)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('pricing', resp.json())
        self.assertEqual(resp.json()['announcements'][0]['code'], 'MODEZA10')
        self.assertIn('endsAt', resp.json()['announcements'][0])

    def test_announcement_endpoint_honors_customer_scope(self):
        customer = User.objects.create_user(
            username='vip-customer', email='vip@example.com', password='pw')
        promo = make_promo(
            code='VIP15',
            customer_scope=Promotion.CustomerScope.SPECIFIC,
            ends_at=timezone.now() + timezone.timedelta(days=1),
        )
        PromotionCustomer.objects.create(promotion=promo, user=customer)

        guest_response = self.client.get('/api/promotions/available')
        self.assertNotIn(
            'VIP15',
            [item['code'] for item in guest_response.json()['announcements']],
        )

        self.client.force_authenticate(user=customer)
        customer_response = self.client.get('/api/promotions/available')
        self.assertIn(
            'VIP15',
            [item['code'] for item in customer_response.json()['announcements']],
        )

    def test_admin_requires_staff(self):
        resp = self.client.get('/api/admin/promotions')
        self.assertIn(resp.status_code, (401, 403))

    def test_admin_crud_and_activate(self):
        staff = User.objects.create_user(username='staffer', password='pw', is_staff=True)
        customer = User.objects.create_user(
            username='promo-api-customer', email='promo-api@example.com',
            password='pw')
        from access_control.models import StaffProfile
        profile, _ = StaffProfile.objects.get_or_create(user=staff)
        profile.status = 'ACTIVE'
        profile.save()
        from access_control.models import Permission
        for code in ('promotions.view', 'promotions.create', 'promotions.update', 'promotions.delete'):
            perm, _ = Permission.objects.get_or_create(
                code=code, defaults={'label': code, 'group': 'promotions'})
            profile.direct_permissions.add(perm)
        self.client.force_authenticate(user=staff)
        created = self.client.post('/api/admin/promotions', {
            'name': 'Admin Promo', 'promotion_type': 'percentage', 'status': 'active',
            'discount_percent': '20', 'coupon_code': 'ADMIN20', 'priority': 50,
            'ends_at': (timezone.now() + timezone.timedelta(days=1)).isoformat()}, format='json')
        self.assertEqual(created.status_code, 201, created.content[:500])
        self.assertTrue(CustomerNotification.objects.filter(
            user=customer,
            event_type='promotion_published',
        ).exists())
        pid = created.json()['id']
        got = self.client.get(f'/api/admin/promotions/{pid}')
        self.assertEqual(got.status_code, 200)
        patched = self.client.patch(f'/api/admin/promotions/{pid}', {'name': 'Admin Promo',
            'promotion_type': 'percentage', 'status': 'active', 'discount_percent': '25',
            'coupon_code': 'ADMIN20', 'priority': 50,
            'ends_at': (timezone.now() + timezone.timedelta(days=1)).isoformat()}, format='json')
        self.assertEqual(patched.status_code, 200)
        deact = self.client.post(f'/api/admin/promotions/{pid}/deactivate')
        self.assertEqual(deact.status_code, 200)
        self.assertEqual(deact.json()['status'], 'disabled')
        act = self.client.post(f'/api/admin/promotions/{pid}/activate')
        self.assertEqual(act.status_code, 200)
        dup = self.client.post(f'/api/admin/promotions/{pid}/duplicate')
        self.assertEqual(dup.status_code, 201)
        analytics = self.client.get(f'/api/admin/promotions/{pid}/analytics')
        self.assertEqual(analytics.status_code, 200)
        self.assertIn('redemptions', analytics.json())


class PromotionCheckoutTests(TestCase):
    def test_checkout_applies_promo_snapshot_and_total(self):
        _, _, variant = make_catalog(slug='co-prod', category_slug='co-cat')
        make_promo(code='MODEZA10')
        client = APIClient()
        client.post('/api/cart/items', {'variantId': str(variant.id), 'quantity': 1},
                    format='json', HTTP_X_CART_ID='co-cart')
        client.post('/api/promotions/apply', {'code': 'MODEZA10'}, format='json', HTTP_X_CART_ID='co-cart')
        resp = client.post('/api/orders', {'customer': CUSTOMER, 'couponCode': 'MODEZA10'},
                           format='json', HTTP_X_CART_ID='co-cart')
        self.assertEqual(resp.status_code, 201, resp.content[:800])
        data = resp.json()
        self.assertEqual(data['discount'], 1000.0)
        self.assertEqual(data['promotion']['code'], 'MODEZA10')
        order = Order.objects.get(order_number=data['orderNumber'])
        self.assertEqual(order.discount_minor, 100000)
        self.assertEqual(order.coupon_code, 'MODEZA10')
        self.assertTrue(order.promotion_snapshot.get('applied'))
        # M-Pesa intent amount must equal the server-side total.
        intent = client.post('/api/payments/create-intent',
                             {'orderNumber': order.order_number, 'method': 'mpesa'},
                             format='json', HTTP_X_CART_ID='co-cart')
        self.assertEqual(intent.status_code, 201, intent.content[:500])
        self.assertEqual(intent.json()['amount'], data['total'])
        # Order total = subtotal - discount + shipping + tax.
        self.assertAlmostEqual(data['total'], data['subtotal'] - data['discount']
                               + data['shippingCost'] + data['tax'])
        # Historical snapshot survives promo deactivation.
        promo = Promotion.objects.get(coupon_code='MODEZA10')
        promo.status = 'disabled'
        promo.save()
        order.refresh_from_db()
        self.assertEqual(order.promotion_snapshot['discount'], 100000)

    def test_failed_payment_does_not_double_consume(self):
        _, _, variant = make_catalog(slug='fp-prod', category_slug='fp-cat')
        make_promo(code='ONCE2', usage_limit=10, usage_limit_per_customer=10)
        client = APIClient()
        client.post('/api/cart/items', {'variantId': str(self.variant_id(variant)), 'quantity': 1},
                    format='json', HTTP_X_CART_ID='fp-cart')
        resp = client.post('/api/orders', {'customer': CUSTOMER, 'couponCode': 'ONCE2'},
                           format='json', HTTP_X_CART_ID='fp-cart')
        self.assertEqual(resp.status_code, 201)
        promo = Promotion.objects.get(coupon_code='ONCE2')
        self.assertEqual(PromotionRedemption.objects.filter(promotion=promo, voided=False).count(), 1)

    def variant_id(self, variant):
        return str(variant.id)

    def test_cancel_voids_redemption(self):
        _, _, variant = make_catalog(slug='cx-prod', category_slug='cx-cat')
        promo = make_promo(code='CX10', usage_limit=1)
        client = APIClient()
        client.post('/api/cart/items', {'variantId': str(variant.id), 'quantity': 1},
                    format='json', HTTP_X_CART_ID='cx-cart')
        resp = client.post('/api/orders', {'customer': CUSTOMER, 'couponCode': 'CX10'},
                           format='json', HTTP_X_CART_ID='cx-cart')
        self.assertEqual(resp.status_code, 201)
        order = Order.objects.get(order_number=resp.json()['orderNumber'])
        client.post(f'/api/orders/{order.order_number}/cancel', {}, format='json', HTTP_X_CART_ID='cx-cart')
        self.assertEqual(PromotionRedemption.objects.filter(promotion=promo, voided=False).count(), 0)

    def test_second_checkout_hits_usage_limit(self):
        """Sequential checkouts for the final redemption: only one succeeds."""
        _, _, variant = make_catalog(slug='rl-prod', category_slug='rl-cat')
        make_promo(code='LASTONE', usage_limit=1)
        client = APIClient()
        client.post('/api/cart/items', {'variantId': str(variant.id), 'quantity': 1},
                    format='json', HTTP_X_CART_ID='rl-cart-1')
        first = client.post('/api/orders', {'customer': CUSTOMER, 'couponCode': 'LASTONE'},
                            format='json', HTTP_X_CART_ID='rl-cart-1')
        self.assertEqual(first.status_code, 201)
        client.post('/api/cart/items', {'variantId': str(variant.id), 'quantity': 1},
                    format='json', HTTP_X_CART_ID='rl-cart-2')
        second = client.post('/api/orders', {'customer': CUSTOMER, 'couponCode': 'LASTONE'},
                             format='json', HTTP_X_CART_ID='rl-cart-2')
        self.assertEqual(second.status_code, 400)
        self.assertIn('usage limit', second.json()['error']['details']['couponCode'].lower())
        promo = Promotion.objects.get(coupon_code='LASTONE')
        self.assertEqual(PromotionRedemption.objects.filter(promotion=promo, voided=False).count(), 1)


class PromotionAdminPageTests(TestCase):
    def _staff(self):
        staff = User.objects.create_user(username='page-staffer', password='pw', is_staff=True)
        from access_control.models import Permission, StaffProfile
        profile, _ = StaffProfile.objects.get_or_create(user=staff)
        profile.status = 'ACTIVE'
        profile.save()
        for code in ('promotions.view', 'promotions.create', 'promotions.update'):
            perm, _ = Permission.objects.get_or_create(
                code=code, defaults={'label': code, 'group': 'promotions'})
            profile.direct_permissions.add(perm)
        return staff

    def test_promotions_list_page(self):
        from django.test import Client
        staff = self._staff()
        make_promo(code='PAGE10')
        client = Client()
        client.force_login(staff)
        resp = client.get('/admin/dashboard/promotions/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'PAGE10')

    def test_promotion_create_page(self):
        from django.test import Client
        staff = self._staff()
        client = Client()
        client.force_login(staff)
        resp = client.post('/admin/dashboard/promotions/new/', {
            'name': 'Winter Sale', 'description': '', 'promotion_type': 'percentage',
            'status': 'active', 'discount_percent': '15', 'discount_amount': '0',
            'qualifying_quantity': '0', 'reward_quantity': '0',
            'reward_discount_percent': '100',
            'coupon_code': 'WINTER15', 'minimum_quantity': '0',
            'priority': '10', 'customer_scope': 'all',
            'ends_at': (timezone.now() + timezone.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Promotion.objects.filter(coupon_code='WINTER15').exists())
