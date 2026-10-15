from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.services import AuditLogService
from catalog.models import Product, ProductVariant

from .errors import QuantityExceededError, VariantUnavailableError
from .models import Cart, CartItem

# Canonical key under which an authenticated customer's persistent cart lives.
# The merge endpoint returns this key in the ``x-cart-id`` header so the
# storefront keeps reusing the same account cart across sessions.
USER_CART_KEY_PREFIX = 'u:'


def user_cart_key(user):
    return f'{USER_CART_KEY_PREFIX}{user.pk}'


def get_or_create_cart(cart_key, user=None):
    if cart_key.startswith(USER_CART_KEY_PREFIX):
        if user is None or cart_key != user_cart_key(user):
            raise PermissionDenied('You cannot access this cart.')
    cart, _ = Cart.objects.get_or_create(
        cart_key=cart_key, defaults={'user': user})
    if cart.user_id is not None and (user is None or cart.user_id != user.pk):
        raise PermissionDenied('You cannot access this cart.')
    if user and cart.user_id is None:
        cart.user = user
        cart.save(update_fields=['user', 'updated_at'])
    return cart


def get_variant_for_cart(variant_id):
    try:
        return ProductVariant.objects.select_related('product').get(
            id=variant_id,
            is_active=True,
            product__status=Product.Status.ACTIVE,
            product__category__is_active=True,
        )
    except ProductVariant.DoesNotExist as exc:
        raise VariantUnavailableError(variant_id=variant_id) from exc


@transaction.atomic
def add_item(cart, variant_id, quantity):
    if quantity < 1:
        raise ValidationError({'quantity': 'Quantity must be at least 1.'})
    variant = get_variant_for_cart(variant_id)
    variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    item, created = CartItem.objects.select_for_update().get_or_create(
        cart=cart, variant=variant, defaults={'quantity': quantity})
    if created:
        prior_quantity = None
        total_quantity = quantity
    else:
        prior_quantity = item.quantity
        total_quantity = quantity + item.quantity
    if total_quantity > variant.stock_quantity:
        raise QuantityExceededError(
            variant_id=variant.pk,
            available=variant.stock_quantity,
            requested=total_quantity,
        )
    item.quantity = total_quantity
    item.save(update_fields=['quantity'])
    AuditLogService.log(
        'cart_item_added',
        category='orders',
        object_type='product_variant',
        object_id=variant.pk,
        object_repr=variant.sku,
        metadata={
            'product': variant.product.name,
            'variant_sku': variant.sku,
            'quantity': item.quantity,
            'created': created,
            'prior_quantity': prior_quantity,
        },
        description=f'Added {variant.sku} to cart ({item.quantity} units).',
    )
    return cart


@transaction.atomic
def update_item(cart, item_id, quantity):
    if quantity < 1:
        raise ValidationError({'quantity': 'Quantity must be at least 1.'})
    try:
        item = CartItem.objects.select_for_update().select_related(
            'variant').get(id=item_id, cart=cart)
    except CartItem.DoesNotExist as exc:
        raise ValidationError({'itemId': 'Cart item was not found.'}) from exc
    variant = get_variant_for_cart(item.variant_id)
    variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    if quantity > variant.stock_quantity:
        raise QuantityExceededError(
            variant_id=variant.pk,
            available=variant.stock_quantity,
            requested=quantity,
        )
    prior_quantity = item.quantity
    item.quantity = quantity
    item.save(update_fields=['quantity'])
    AuditLogService.log(
        'cart_item_updated',
        category='orders',
        object_type='product_variant',
        object_id=variant.pk,
        object_repr=variant.sku,
        metadata={
            'product': variant.product.name,
            'variant_sku': variant.sku,
            'from_quantity': prior_quantity,
            'to_quantity': quantity,
        },
        description=f'Updated {variant.sku} quantity to {quantity}.',
    )
    return cart


@transaction.atomic
def merge_carts(user, guest_key):
    """Merge a guest cart into the user's persistent account cart.

    Strips lines that are no longer purchasable and clamps quantities to the
    current stock so a login never drops a silently corrupted cart. The
    account cart is keyed canonically (``u:<user_id>``) so it persists across
    sessions; the guest cart is deleted once its lines have been adopted.
    Returns ``(cart, summary)`` where ``summary`` describes what happened:

    ``merged``   lines moved into the account cart,
    ``clamped``  subset of ``merged`` reduced to the available stock,
    ``skipped``  lines dropped (unavailable or out of stock),
    ``skippedItems`` per-line reasons for dropped lines (never exposes SKUs).
    """
    target_key = user_cart_key(user)
    target, _ = Cart.objects.select_for_update().get_or_create(
        cart_key=target_key, defaults={'user': user})
    summary = {'merged': 0, 'clamped': 0, 'skipped': 0, 'skippedItems': []}

    if guest_key and guest_key != target_key:
        guest = Cart.objects.filter(
            cart_key=guest_key).exclude(pk=target.pk).first()
        if guest is not None:
            is_other_users_cart = (
                guest.user_id is not None
                and guest.user_id != user.pk
                and guest_key.startswith(USER_CART_KEY_PREFIX)
            )
            if is_other_users_cart:
                guest = None
        if guest is not None and guest.items.exists():
            guest_item_ids = list(
                guest.items.values_list('id', flat=True))
            for item in CartItem.objects.select_for_update().select_related(
                    'variant__product').filter(id__in=guest_item_ids):
                _merge_cart_item(target, item, summary)
            if not getattr(target, 'coupon_code', '') and getattr(guest, 'coupon_code', ''):
                target.coupon_code = guest.coupon_code
            guest.delete()
            target.save(update_fields=['updated_at'] + (['coupon_code'] if getattr(target, 'coupon_code', '') else []))

    if summary['merged'] or summary['clamped'] or summary['skipped']:
        AuditLogService.log(
            'cart_merged',
            category='orders',
            object_type='cart',
            object_id=target.cart_key,
            object_repr=f'Cart {target.cart_key}',
            metadata={
                'source_cart_key': guest_key or '',
                'merged': summary['merged'],
                'clamped': summary['clamped'],
                'skipped': summary['skipped'],
            },
            description=(
                f'Merged guest cart into account cart ({summary["merged"]} '
                f'lines, {summary["clamped"]} clamped, '
                f'{summary["skipped"]} skipped).'),
        )
    return target, summary


def _merge_cart_item(target, item, summary):
    try:
        variant = get_variant_for_cart(item.variant_id)
    except VariantUnavailableError:
        summary['skipped'] += 1
        summary['skippedItems'].append({
            'variantId': str(item.variant_id),
            'productName': item.variant.product.name,
            'reason': 'unavailable',
        })
        return
    variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    existing = CartItem.objects.select_for_update().filter(
        cart=target, variant=variant).first()
    current = existing.quantity if existing else 0
    desired = current + item.quantity
    reason = 'merged'
    if desired > variant.stock_quantity:
        if variant.stock_quantity <= 0:
            summary['skipped'] += 1
            summary['skippedItems'].append({
                'variantId': str(variant.pk),
                'productName': variant.product.name,
                'reason': 'out_of_stock',
            })
            return
        desired = variant.stock_quantity
        reason = 'clamped'
        summary['clamped'] += 1
    if existing:
        if existing.quantity != desired:
            existing.quantity = desired
            existing.save(update_fields=['quantity'])
    else:
        CartItem.objects.create(cart=target, variant=variant, quantity=desired)
    summary['merged'] += 1
    return reason
