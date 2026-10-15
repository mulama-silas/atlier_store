"""Order tools — ownership mirrors ``orders.views`` exactly.

A customer (or guest with the cart key that placed the order) may only see
their own orders. Internal order UUIDs are never exposed; only the public
``order_number``.
"""
from orders.models import Order

_UNAUTHORIZED = {'error': {'code': 'not_authorized',
                           'message': 'Orders are only available to the '
                                      'customer who placed them.'}}
_NOT_FOUND = {'error': {'code': 'not_found', 'message': 'Order not found.'}}


def _may_view(order, context):
    if context.user_id is not None:
        return order.user_id == context.user_id
    return bool(context.cart_key and order.user_id is None and order.cart_id
                and order.cart.user_id is None
                and order.cart.cart_key == context.cart_key)


def _serialize(order):
    return {
        'orderNumber': order.order_number,
        'status': order.status,
        'paymentStatus': order.payment_status,
        'paymentMethod': order.payment_method,
        'shippingMethod': order.shipping_method,
        'total': round(order.total_minor / 100, 2),
        'currency': order.currency,
        'createdAt': order.created_at.isoformat(),
        'items': [
            {'name': item.product_name,
             'size': item.variant_size,
             'colour': item.variant_color,
             'quantity': item.quantity,
             'lineTotal': round(item.line_total_minor / 100, 2)}
            for item in order.items.all()[:20]
        ],
    }


def _lookup(order_number, context):
    order = Order.objects.select_related('cart').prefetch_related('items').filter(
        order_number=order_number or '').first()
    if order is None:
        return None, _NOT_FOUND
    if not _may_view(order, context):
        return None, _UNAUTHORIZED
    return order, None


def get_order_status(*, context=None, order_number=''):
    order, error = _lookup(order_number, context)
    if error is not None:
        return error
    payload = _serialize(order)
    payload['message'] = (
        f'Order {order.order_number} is {order.status}. '
        f'Payment is {order.payment_status}.')
    return payload


def get_customer_orders(*, context=None):
    if context is None or (context.user_id is None and not context.cart_key):
        return {'error': {'code': 'auth_required',
                          'message': 'Sign in to see your orders, or provide '
                                     'an order number.'}}
    base = Order.objects.select_related('cart').prefetch_related('items').all()
    if context.user_id is not None:
        orders = base.filter(user_id=context.user_id)
    else:
        orders = base.filter(user__isnull=True, cart__user__isnull=True,
                             cart__cart_key=context.cart_key)
    orders = orders.order_by('-created_at')[:10]
    results = [_serialize(o) for o in orders]
    if not results:
        return {'orders': [], 'message': 'No orders found for this account.'}
    return {'orders': results, 'count': len(results)}
