import uuid

from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import SupabaseJWTAuthentication
from audit.services import AuditLogService

from .models import CartItem
from .serializers import CartSerializer
from .services import (
    add_item,
    get_or_create_cart,
    merge_carts,
    update_item,
)


class OptionalSupabaseJWTAuthentication(SupabaseJWTAuthentication):
    """Authenticate valid customer tokens while keeping guest cart calls public."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            return None


def cart_key_from_request(request):
    return request.headers.get('x-cart-id') or str(uuid.uuid4())


def cart_for_request(request):
    return get_or_create_cart(cart_key_from_request(request), request.user if request.user.is_authenticated else None)


def response_with_cart(request, cart, response_status=status.HTTP_200_OK):
    serializer = CartSerializer(cart, context={'request': request})
    response = Response(serializer.data, status=response_status)
    response['x-cart-id'] = cart.cart_key
    return response


class CartView(APIView):
    authentication_classes = [OptionalSupabaseJWTAuthentication]
    permission_classes = []

    def get(self, request):
        return response_with_cart(request, cart_for_request(request))

    def delete(self, request):
        cart = cart_for_request(request)
        item_count = cart.items.count()
        cart.items.all().delete()
        if getattr(cart, 'coupon_code', ''):
            cart.coupon_code = ''
            cart.save(update_fields=['coupon_code', 'updated_at'])
        AuditLogService.log(
            'cart_cleared',
            category='orders',
            object_type='cart',
            object_id=cart.cart_key,
            object_repr=f'Cart {cart.cart_key}',
            metadata={'item_count': item_count},
            description=f'Cleared cart ({item_count} items).',
        )
        return response_with_cart(request, cart)


class CartItemCreateView(APIView):
    authentication_classes = [OptionalSupabaseJWTAuthentication]
    permission_classes = []

    def post(self, request):
        cart = cart_for_request(request)
        variant_id = request.data.get('variantId')
        quantity = request.data.get('quantity')
        if not variant_id or not isinstance(quantity, int):
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'variantId and integer quantity are required.', 'details': {}}}, status=400)
        add_item(cart, variant_id, quantity)
        return response_with_cart(request, cart, status.HTTP_201_CREATED)


class CartItemView(APIView):
    authentication_classes = [OptionalSupabaseJWTAuthentication]
    permission_classes = []

    def patch(self, request, item_id):
        cart = cart_for_request(request)
        quantity = request.data.get('quantity')
        if not isinstance(quantity, int):
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'Integer quantity is required.', 'details': {}}}, status=400)
        update_item(cart, item_id, quantity)
        return response_with_cart(request, cart)

    def delete(self, request, item_id):
        cart = cart_for_request(request)
        item = CartItem.objects.select_related(
            'variant').filter(cart=cart, id=item_id).first()
        if not item:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Cart item was not found.', 'details': {}}}, status=404)
        CartItem.objects.filter(pk=item.pk).delete()
        AuditLogService.log(
            'cart_item_removed',
            category='orders',
            object_type='product_variant',
            object_id=item.variant_id,
            object_repr=item.variant.sku,
            metadata={
                'product': item.variant.product.name,
                'variant_sku': item.variant.sku,
                'quantity': item.quantity,
            },
            description=f'Removed {item.variant.sku} from cart.',
        )
        return response_with_cart(request, cart)


class CartMergeView(APIView):
    """Fold the current guest cart into the authenticated user's cart.

    Requires a valid Supabase session (``Authorization: Bearer``). The guest
    cart is identified by the ``x-cart-id`` header; its adoptable lines move
    into the canonical account cart keyed ``u:<user_id>``, the guest cart is
    deleted, and the response carries the account cart key in ``x-cart-id`` so
    the storefront keeps reusing the same persistent cart.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        cart, summary = merge_carts(request.user, cart_key_from_request(request))
        serializer = CartSerializer(cart, context={'request': request})
        payload = dict(serializer.data)
        payload['mergeSummary'] = summary
        response = Response(payload, status=status.HTTP_200_OK)
        response['x-cart-id'] = cart.cart_key
        return response
