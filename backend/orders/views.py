from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import AuditLogService

from .models import Order
from .serializers import OrderSerializer, OrderCreateSerializer
from .services import cancel_order, create_order, mark_received_paid, receive_order, request_refund


def cart_key(request):
    return request.headers.get('x-cart-id')


def can_access_order(request, order):
    if request.user.is_authenticated:
        return order.user_id == request.user.id
    return bool(
        order.user_id is None and order.cart and order.cart.user_id is None
        and cart_key(request) and order.cart.cart_key == cart_key(request))


class OrdersView(APIView):
    throttle_scope = 'orders'

    def get(self, request):
        base = Order.objects.select_related('cart').prefetch_related('items')
        if request.user.is_authenticated:
            orders = base.filter(user_id=request.user.id)
        elif cart_key(request):
            orders = base.filter(user__isnull=True, cart__user__isnull=True,
                                 cart__cart_key=cart_key(request))
        else:
            orders = base.none()
        orders = orders.order_by('-created_at')
        return Response({
            'count': orders.count(),
            'results': OrderSerializer(
                orders, many=True, context={'request': request}).data,
        })

    def post(self, request):
        if not cart_key(request):
            return Response({'error': {'code': 'CART_REQUIRED', 'message': 'x-cart-id is required.', 'details': {}}}, status=400)
        serializer = OrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'Request validation failed.', 'details': serializer.errors}}, status=400)
        order = create_order(cart_key(request), serializer.validated_data,
                             request.user if request.user.is_authenticated else None)
        return Response(OrderSerializer(order, context={'request': request}).data, status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    def get(self, request, order_number):
        order = Order.objects.prefetch_related('items', 'reservations').select_related(
            'cart').filter(order_number=order_number).first()
        if not order:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Order was not found.', 'details': {}}}, status=404)
        if not can_access_order(request, order):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'You cannot access this order.', 'details': {}}}, status=403)
        AuditLogService.log(
            'order_details_viewed',
            object_type='order',
            object_id=order.pk,
            object_repr=order.order_number,
            category='orders',
            metadata={'status': order.status},
            description=f'Order {order.order_number} details viewed.',
        )
        return Response(OrderSerializer(order, context={'request': request}).data)

    def post(self, request, order_number):
        if request.path.endswith('/cancel'):
            return self.cancel(request, order_number)
        if request.path.endswith('/receive'):
            return self.receive(request, order_number)
        if request.path.endswith('/mark-received-paid'):
            return self.mark_received_paid(request, order_number)
        if request.path.endswith('/return'):
            return self.request_return(request, order_number)
        return Response({'error': {'code': 'METHOD_NOT_ALLOWED', 'message': 'Unsupported operation.', 'details': {}}}, status=405)

    def cancel(self, request, order_number):
        order = Order.objects.select_related('cart').filter(
            order_number=order_number).first()
        if not order:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Order was not found.', 'details': {}}}, status=404)

        if not can_access_order(request, order):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'You cannot cancel this order.', 'details': {}}}, status=403)

        order = cancel_order(order)
        return Response(OrderSerializer(order, context={'request': request}).data)

    def receive(self, request, order_number):
        order = Order.objects.select_related('cart').filter(
            order_number=order_number).first()
        if not order:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Order was not found.', 'details': {}}}, status=404)

        if not can_access_order(request, order):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'You cannot mark this order as received.', 'details': {}}}, status=403)

        order = receive_order(order)
        return Response(OrderSerializer(order, context={'request': request}).data)

    def mark_received_paid(self, request, order_number):
        order = Order.objects.select_related('cart').filter(
            order_number=order_number).first()
        if not order:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Order was not found.', 'details': {}}}, status=404)

        if not can_access_order(request, order):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'You cannot mark this order as received and paid.', 'details': {}}}, status=403)

        order = mark_received_paid(order)
        return Response(OrderSerializer(order, context={'request': request}).data)

    def request_return(self, request, order_number):
        order = Order.objects.select_related('cart').filter(
            order_number=order_number).first()
        if not order:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Order was not found.', 'details': {}}}, status=404)

        if request.user.is_authenticated:
            allowed = order.user_id == request.user.id
        else:
            allowed = bool(
                cart_key(request) and order.cart and order.cart.cart_key == cart_key(request))

        if not allowed:
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'You cannot request a refund for this order.', 'details': {}}}, status=403)

        reason = request.data.get('reason', '') if isinstance(request.data, dict) else ''
        if reason and not isinstance(reason, str):
            reason = ''
        order = request_refund(order, reason)
        return Response(OrderSerializer(order, context={'request': request}).data)
