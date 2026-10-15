import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Category, Product, ProductVariant
from cart.models import Cart, CartItem

TEST_SECRET = 'test-secret-that-is-at-least-32-bytes'


def make_token(subject='user-123', role='customer'):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            'sub': subject,
            'email': f'{subject}@example.com',
            'aud': 'authenticated',
            'iat': now,
            'exp': now + timedelta(minutes=5),
            'app_metadata': {'role': role},
        },
        TEST_SECRET,
        algorithm='HS256',
    )


@override_settings(
    SUPABASE_JWT_SECRET=TEST_SECRET,
    SUPABASE_JWT_ISSUER='',
)
class CartApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        category = Category.objects.create(name='Tops', slug=f'tops-{unique}')
        product = Product.objects.create(
            category=category,
            name='Linen Top',
            slug=f'linen-top-{unique}',
            description='A breathable linen top for warm days.',
            price_minor=12000,
            images=['/media/products/test-linen-top.jpg'],
            status=Product.Status.ACTIVE,
        )
        self.variant = ProductVariant.objects.create(
            product=product, sku='LINEN-S', size='S', stock_quantity=2)

    def add_guest_item(self, cart_key, quantity=2):
        return self.client.post(
            '/api/cart/items',
            {'variantId': str(self.variant.id), 'quantity': quantity},
            format='json',
            HTTP_X_CART_ID=cart_key,
        )

    def test_account_cart_key_cannot_be_claimed_by_guest_or_another_user(self):
        from django.contrib.auth import get_user_model
        from rest_framework.exceptions import PermissionDenied
        from cart.services import get_or_create_cart

        owner = get_user_model().objects.create_user(username='cart-owner')
        other = get_user_model().objects.create_user(username='cart-other')
        key = f'u:{owner.pk}'
        get_or_create_cart(key, owner)

        with self.assertRaises(PermissionDenied):
            get_or_create_cart(key)
        with self.assertRaises(PermissionDenied):
            get_or_create_cart(key, other)

        guest_response = self.client.get('/api/cart', HTTP_X_CART_ID=key)
        self.assertEqual(guest_response.status_code, 403)
        self.client.force_authenticate(user=owner)
        owner_response = self.client.get('/api/cart', HTTP_X_CART_ID=key)
        self.assertEqual(owner_response.status_code, 200)
        self.client.force_authenticate(user=other)
        other_response = self.client.get('/api/cart', HTTP_X_CART_ID=key)
        self.assertEqual(other_response.status_code, 403)

    def test_guest_cart_persists_by_header_and_returns_totals(self):
        headers = {'HTTP_X_CART_ID': 'cart_test_123'}
        response = self.client.post(
            '/api/cart/items', {'variantId': str(self.variant.id), 'quantity': 2}, format='json', **headers)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['x-cart-id'], 'cart_test_123')
        self.assertEqual(response.json()['itemCount'], 2)
        self.assertEqual(response.json()['subtotal'], 240)

        persisted = self.client.get('/api/cart', **headers)
        self.assertEqual(len(persisted.json()['items']), 1)

    def test_cart_returns_absolute_product_image_for_cart_items(self):
        response = self.client.post(
            '/api/cart/items',
            {'variantId': str(self.variant.id), 'quantity': 1},
            format='json',
            HTTP_X_CART_ID='cart_image_test',
        )

        self.assertEqual(response.status_code, 201)
        product_payload = response.json()['items'][0]['product']
        self.assertEqual(
            product_payload['image'], 'http://testserver/media/products/test-linen-top.jpg')

    def test_guest_cart_ignores_invalid_bearer_token(self):
        response = self.client.post(
            '/api/cart/items',
            {'variantId': str(self.variant.id), 'quantity': 1},
            format='json',
            HTTP_X_CART_ID='cart_invalid_token_test',
            HTTP_AUTHORIZATION='Bearer invalid-token',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['x-cart-id'], 'cart_invalid_token_test')

    def test_cart_rejects_quantity_above_stock_with_structured_code(self):
        response = self.client.post(
            '/api/cart/items',
            {'variantId': str(self.variant.id), 'quantity': 3},
            format='json',
            HTTP_X_CART_ID='cart_stock_test',
        )

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body['error']['code'], 'QUANTITY_EXCEEDS_STOCK')
        self.assertEqual(body['error']['details']['available'], 2)
        self.assertIn('Only 2', body['error']['details']['quantity'])

    def test_rejected_add_leaves_cart_unchanged(self):
        self.add_guest_item('cart_rollback_test', quantity=1)

        response = self.client.post(
            '/api/cart/items',
            {'variantId': str(self.variant.id), 'quantity': 5},
            format='json',
            HTTP_X_CART_ID='cart_rollback_test',
        )

        self.assertEqual(response.status_code, 409)
        cart = Cart.objects.get(cart_key='cart_rollback_test')
        item = cart.items.get()
        self.assertEqual(item.quantity, 1)

    def test_update_item_rejects_quantity_above_stock(self):
        self.add_guest_item('cart_update_stock_test', quantity=1)
        item_id = Cart.objects.get(
            cart_key='cart_update_stock_test').items.get().id

        response = self.client.patch(
            f'/api/cart/items/{item_id}',
            {'quantity': 5},
            format='json',
            HTTP_X_CART_ID='cart_update_stock_test',
        )

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body['error']['code'], 'QUANTITY_EXCEEDS_STOCK')
        self.assertEqual(body['error']['details']['available'], 2)
        item = Cart.objects.get(
            cart_key='cart_update_stock_test').items.get()
        self.assertEqual(item.quantity, 1)

    def test_update_item_revalidates_variant_availability(self):
        self.add_guest_item('cart_update_revalidate_test', quantity=1)
        item_id = Cart.objects.get(
            cart_key='cart_update_revalidate_test').items.get().id
        self.variant.is_active = False
        self.variant.save(update_fields=['is_active'])

        response = self.client.patch(
            f'/api/cart/items/{item_id}',
            {'quantity': 2},
            format='json',
            HTTP_X_CART_ID='cart_update_revalidate_test',
        )

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body['error']['code'], 'VARIANT_NOT_AVAILABLE')
        item = Cart.objects.get(
            cart_key='cart_update_revalidate_test').items.get()
        self.assertEqual(item.quantity, 1)

    def test_update_missing_item_returns_not_found(self):
        response = self.client.patch(
            f'/api/cart/items/{uuid.uuid4()}',
            {'quantity': 2},
            format='json',
            HTTP_X_CART_ID='cart_missing_item_test',
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body['error']['code'], 'VALIDATION_ERROR')
        self.assertIn('itemId', body['error']['details'])


@override_settings(
    SUPABASE_JWT_SECRET=TEST_SECRET,
    SUPABASE_JWT_ISSUER='',
)
class CartMergeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='supabase_merge-123', email='merge@example.com')
        unique = uuid.uuid4().hex[:8]
        category = Category.objects.create(name='Tops', slug=f'tops-{unique}')
        product = Product.objects.create(
            category=category,
            name='Silk Blouse',
            slug=f'silk-blouse-{unique}',
            description='A refined silk blouse.',
            price_minor=18000,
            images=[],
            status=Product.Status.ACTIVE,
        )
        self.variant = ProductVariant.objects.create(
            product=product, sku='SILK-M', size='M', stock_quantity=4)
        self.other = ProductVariant.objects.create(
            product=product, sku='SILK-L', size='L', stock_quantity=3)

    def auth(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {make_token(subject="merge-123")}')

    def guest_cart_key(self):
        return f'cart_merge_{uuid.uuid4().hex[:8]}'

    def add_line(self, cart_key, variant, quantity):
        return self.client.post(
            '/api/cart/items',
            {'variantId': str(variant.id), 'quantity': quantity},
            format='json',
            HTTP_X_CART_ID=cart_key,
        )

    def test_merge_requires_authentication(self):
        response = self.client.post(
            '/api/cart/merge',
            HTTP_X_CART_ID='cart_anon_merge',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()['error']['code'], 'AUTHENTICATION_REQUIRED')

    def test_merge_moves_guest_items_into_account_cart(self):
        guest_key = self.guest_cart_key()
        self.add_line(guest_key, self.variant, 2)
        self.add_line(guest_key, self.other, 1)
        self.auth()

        response = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['mergeSummary']['merged'], 2)
        self.assertEqual(body['mergeSummary']['skipped'], 0)
        self.assertEqual(body['itemCount'], 3)
        target_key = response['x-cart-id']
        self.assertEqual(target_key, f'u:{self.user.pk}')
        self.assertEqual(CartItem.objects.count(), 2)
        self.assertFalse(Cart.objects.filter(cart_key=guest_key).exists())

        persisted = self.client.get('/api/cart', HTTP_X_CART_ID=target_key)
        self.assertEqual(persisted.json()['itemCount'], 3)

    def test_merge_clamps_quantities_to_stock(self):
        guest_key = self.guest_cart_key()
        self.add_line(guest_key, self.variant, 2)
        self.variant.stock_quantity = 1
        self.variant.save(update_fields=['stock_quantity'])
        self.auth()

        response = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['mergeSummary']['merged'], 1)
        self.assertEqual(body['mergeSummary']['clamped'], 1)
        self.assertEqual(body['items'][0]['quantity'], 1)

    def test_merge_accumulates_into_existing_account_cart(self):
        guest_key = self.guest_cart_key()
        self.add_line(guest_key, self.variant, 1)
        self.auth()
        first = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)
        target_key = first['x-cart-id']
        self.assertEqual(first.json()['mergeSummary']['merged'], 1)

        second_guest = self.guest_cart_key()
        self.client.credentials()
        self.add_line(second_guest, self.variant, 2)
        self.auth()

        second = self.client.post(
            '/api/cart/merge', HTTP_X_CART_ID=second_guest)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['mergeSummary']['merged'], 1)
        self.assertEqual(second.json()['items'][0]['quantity'], 3)
        self.assertEqual(second['x-cart-id'], target_key)

    def test_merge_skips_unavailable_variants(self):
        guest_key = self.guest_cart_key()
        self.add_line(guest_key, self.variant, 1)
        self.add_line(guest_key, self.other, 1)
        self.other.is_active = False
        self.other.save(update_fields=['is_active'])
        self.auth()

        response = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['mergeSummary']['merged'], 1)
        self.assertEqual(body['mergeSummary']['skipped'], 1)
        self.assertEqual(
            body['mergeSummary']['skippedItems'][0]['reason'], 'unavailable')
        self.assertEqual(len(body['items']), 1)

    def test_merge_skips_repeated_merge(self):
        guest_key = self.guest_cart_key()
        self.add_line(guest_key, self.variant, 2)
        self.auth()

        first = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)
        self.assertEqual(first.json()['mergeSummary']['merged'], 1)

        second = self.client.post('/api/cart/merge', HTTP_X_CART_ID=guest_key)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['mergeSummary']['merged'], 0)
        self.assertEqual(second.json()['itemCount'], 2)

    def test_merge_does_not_touch_another_users_cart(self):
        other_user = get_user_model().objects.create_user(
            username='supabase_merge-456', email='other@example.com')
        other_cart = Cart.objects.create(
            cart_key=f'u:{other_user.pk}', user=other_user)
        CartItem.objects.create(
            cart=other_cart, variant=self.variant, quantity=1)
        self.auth()

        response = self.client.post(
            '/api/cart/merge', HTTP_X_CART_ID=other_cart.cart_key)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['mergeSummary']['merged'], 0)
        self.assertEqual(body['itemCount'], 0)
        self.assertTrue(Cart.objects.filter(pk=other_cart.pk).exists())
        self.assertEqual(
            CartItem.objects.filter(cart=other_cart).count(), 1)
