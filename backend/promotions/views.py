"""Customer-facing promotion endpoints. Django is authoritative."""
import logging

from django.db import transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import SupabaseJWTAuthentication
from audit.services import AuditLogService
from cart.models import Cart

from .models import Promotion, normalize_coupon_code
from .serializers import promotion_to_dict
from .services import (
    FRIENDLY,
    candidate_promotions,
    check_customer_scope,
    price_cart,
    validate_coupon,
)

logger = logging.getLogger('promotions.views')


def _cart_key(request):
    from cart.views import cart_key_from_request, get_or_create_cart
    key = request.headers.get('x-cart-id')
    if not key:
        return None, None
    user = request.user if getattr(request.user, 'is_authenticated', False) else None
    cart = get_or_create_cart(key, user)
    return cart, key


def _pricing_payload(breakdown):
    applied = breakdown.get('applied') or []
    primary = applied[0] if applied else None
    return {
        'subtotal': breakdown['subtotal'] / 100,
        'eligibleSubtotal': breakdown.get('eligible_subtotal', 0) / 100,
        'discount': breakdown['discount'] / 100,
        'shipping': breakdown['shipping'] / 100,
        'shippingDiscount': breakdown.get('shipping_discount', 0) / 100,
        'tax': breakdown.get('tax', 0) / 100,
        'total': breakdown['total'] / 100,
        'currency': 'KES',
        'promotion': (
            {'code': primary['code'], 'name': primary['name'],
             'discount': primary['discount'] / 100, 'type': primary['type']}
            if primary else None
        ),
        'appliedPromotions': [
            {'code': a['code'], 'name': a['name'], 'type': a['type'],
             'discount': a['discount'] / 100,
             'shippingDiscount': a.get('shipping_discount', 0) / 100}
            for a in applied
        ],
    }


def _error(code, status=400):
    return Response({'error': {'code': code, 'message': FRIENDLY.get(code, 'Invalid promotion code.'),
                               'details': {}}}, status=status)


class PromotionApplyView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = 'orders'

    @transaction.atomic
    def post(self, request):
        cart, key = _cart_key(request)
        if cart is None:
            return Response({'error': {'code': 'CART_REQUIRED', 'message': 'x-cart-id is required.',
                                       'details': {}}}, status=400)
        code = (request.data.get('code') or request.data.get('couponCode') or '').strip()
        shipping_method = (request.data.get('shippingMethod') or 'standard').strip() or 'standard'
        if not code:
            return _error('INVALID_CODE')
        normalized = normalize_coupon_code(code)
        cart = Cart.objects.select_for_update().filter(pk=cart.pk).first() or cart
        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        breakdown, err = validate_coupon(normalized, cart, user=user, shipping_method=shipping_method)
        if err:
            AuditLogService.log('promotion_redemption_failed', object_type='promotion',
                                object_repr=normalized, category='orders', result='failure',
                                metadata={'code': err, 'cart_key': key},
                                description=f'Coupon {normalized} rejected: {err}.')
            return _error(err, status=422)
        cart.coupon_code = normalized
        cart.save(update_fields=['coupon_code', 'updated_at'])
        AuditLogService.log('promotion_redeemed', object_type='promotion',
                            object_repr=normalized, category='orders',
                            metadata={'cart_key': key, 'discount_minor': breakdown['discount']},
                            description=f'Coupon {normalized} applied to cart.')
        payload = _pricing_payload(breakdown)
        return Response(payload)


class PromotionRemoveView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = 'orders'

    def post(self, request):
        cart, key = _cart_key(request)
        if cart is None:
            return Response({'error': {'code': 'CART_REQUIRED', 'message': 'x-cart-id is required.',
                                       'details': {}}}, status=400)
        shipping_method = (request.data.get('shippingMethod') or 'standard').strip() or 'standard'
        cart.coupon_code = ''
        cart.save(update_fields=['coupon_code', 'updated_at'])
        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        breakdown = price_cart(cart, user=user, shipping_method=shipping_method, coupon_code='')
        return Response(_pricing_payload(breakdown))


class PromotionAvailableView(APIView):
    authentication_classes = [SupabaseJWTAuthentication, SessionAuthentication]
    permission_classes = []

    def get(self, request):
        from django.db.models import Q
        from django.utils import timezone

        from cart.views import cart_key_from_request, get_or_create_cart
        key = request.headers.get('x-cart-id')
        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        shipping_method = (request.query_params.get('shippingMethod') or 'standard').strip() or 'standard'
        if key:
            cart = get_or_create_cart(key, user)
            breakdown = price_cart(cart, user=user, shipping_method=shipping_method,
                                   coupon_code=getattr(cart, 'coupon_code', '') or '')
            pricing = _pricing_payload(breakdown)
        else:
            pricing = None
        # Public discovery: active automatic promos + coupon promos already
        # applied — never internal IDs, limits, or customer lists.
        promos = candidate_promotions(coupon_normalized='')
        discovery = []
        for promo in promos:
            eligible, _ = check_customer_scope(promo, user)
            if not eligible:
                continue
            badge = _badge(promo)
            discovery.append({'name': promo.name, 'type': promo.promotion_type,
                              'code': '' if promo.is_automatic else 'AVAILABLE_AT_CHECKOUT',
                              'badge': badge, 'automatic': True})
        now = timezone.now()
        announcements = Promotion.objects.filter(
            status=Promotion.Status.ACTIVE,
            ends_at__gt=now,
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        ).prefetch_related('promo_customers').order_by('-priority', '-created_at')
        return Response({
            'pricing': pricing,
            'available': discovery,
            'announcements': [
                {
                    'id': str(promo.pk),
                    'name': promo.name,
                    'description': promo.description,
                    'badge': _badge(promo),
                    'code': promo.coupon_code if not promo.is_automatic else '',
                    'endsAt': promo.ends_at.isoformat() if promo.ends_at else None,
                }
                for promo in announcements
                if check_customer_scope(promo, user)[0]
            ],
        })

    def post(self, request):
        return self.get(request)


def _badge(promo):
    if promo.promotion_type == 'percentage':
        return f'{promo.discount_percent:g}% OFF'
    if promo.promotion_type == 'fixed':
        return f'KES {(promo.discount_amount_minor or 0) / 100:,.0f} OFF'
    if promo.promotion_type == 'free_shipping':
        return 'FREE DELIVERY'
    if promo.promotion_type == 'buy_x_get_y':
        return 'BUY X GET Y'
    if promo.promotion_type == 'buy_x_get_pct':
        return f'{promo.reward_discount_percent:g}% OFF'
    return 'OFFER'
