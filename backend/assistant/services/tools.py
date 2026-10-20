"""Assistant tool registry: function declarations + dispatch.

Only tools registered here are ever offered to Gemini (system prompt rule
11/12 mirrors this list). Every execution goes through :func:`execute`,
which sanitizes arguments, times the call, and converts any exception into
a tool-level error payload — a broken tool must never crash a chat turn.
"""
import time

from .actions import create_support_request, prepare_add_to_cart
from .gemini import ToolExecution
from .order_tools import get_customer_orders, get_order_status
from .policy_tools import get_store_policy
from .product_tools import (check_variant_availability, compare_products,
                            search_products)
from .promotion_tools import get_active_promotions, validate_promotion_code


class ToolContext:
    """Per-request capabilities passed to tools (never to the model)."""

    def __init__(self, user=None, cart_key='', request_id='', ip_address=''):
        self.user = user
        self.user_id = user.pk if getattr(user, 'is_authenticated', False) and user else None
        self.cart_key = cart_key or ''
        self.request_id = request_id
        self.ip_address = ip_address


TOOL_SCHEMAS = [
    {
        'type': 'function',
        'name': 'search_products',
        'description': (
            'Search the Modeza catalog for active products. Returns product '
            'names, prices in KES, colours, sizes and availability. Use for '
            'any "find/show me/looking for" request, budget filters, colour, '
            'category, occasion or sale items.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string',
                          'description': 'Free-text keywords, e.g. "linen dress".'},
                'colour': {'type': 'string',
                           'description': 'Colour filter, e.g. "black".'},
                'size': {'type': 'string',
                         'description': 'Size filter, e.g. "M" or "10".'},
                'category': {'type': 'string',
                             'description': 'Category slug or name, e.g. "dresses".'},
                'min_price_kes': {'type': 'integer',
                                  'description': 'Minimum price in KES.'},
                'max_price_kes': {'type': 'integer',
                                  'description': 'Maximum price in KES.'},
                'in_stock': {'type': 'boolean',
                             'description': 'Only items currently in stock.'},
                'occasion': {'type': 'string',
                             'description': 'Occasion keyword hint, e.g. "wedding".'},
                'collection': {'type': 'string',
                               'description': 'One of: new, best_seller, featured, sale.'},
                'limit': {'type': 'integer',
                          'description': 'How many products to return (default 5, max 10).'},
            },
            'required': [],
        },
    },
    {
        'type': 'function',
        'name': 'compare_products',
        'description': ('Compare specific products side by side: price, '
                        'colours, sizes, availability, badges.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'slugs': {'type': 'array', 'items': {'type': 'string'},
                          'description': 'Product slugs (from search results).'},
            },
            'required': ['slugs'],
        },
    },
    {
        'type': 'function',
        'name': 'check_variant_availability',
        'description': ('Check whether a product has a given size and/or '
                        'colour available. Never returns exact stock levels.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'product': {'type': 'string',
                            'description': 'Product slug (preferred) or product name.'},
                'size': {'type': 'string', 'description': 'Size, e.g. "M".'},
                'colour': {'type': 'string', 'description': 'Colour, e.g. "black".'},
            },
            'required': ['product'],
        },
    },
    {
        'type': 'function',
        'name': 'get_active_promotions',
        'description': ('List currently running promotions and offers. Never '
                        'returns coupon codes; coupon codes are applied at '
                        'checkout.'),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'type': 'function',
        'name': 'validate_promotion_code',
        'description': ('Check whether a coupon code the customer already has '
                        'is currently valid. Does not apply it — codes are '
                        'applied in the cart at checkout.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string', 'description': 'The coupon code to check.'},
            },
            'required': ['code'],
        },
    },
    {
        'type': 'function',
        'name': 'get_order_status',
        'description': ('Fetch status, payment status and items for one order '
                        'by its order number. Only the signed-in customer (or '
                        'the guest who placed it) may see it.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'order_number': {'type': 'string',
                                 'description': 'Order number, e.g. MDZ-2026-000123.'},
            },
            'required': ['order_number'],
        },
    },
    {
        'type': 'function',
        'name': 'get_customer_orders',
        'description': ('List recent orders for the current signed-in '
                        'customer. Use before get_order_status when the '
                        'customer asks about "my order" without a number.'),
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'type': 'function',
        'name': 'get_store_policy',
        'description': ('Official Modeza store policy text: shipping, '
                        'returns, payments, sizing or contact. Always use '
                        'this for policy questions instead of guessing.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'topic': {'type': 'string',
                          'description': 'One of: shipping, returns, payments, sizing, contact.'},
            },
            'required': ['topic'],
        },
    },
    {
        'type': 'function',
        'name': 'prepare_add_to_cart',
        'description': ('Validate that a product/size/colour can be added and '
                        'prepare a ready-to-add action for the customer to '
                        'confirm. Does not modify the cart itself.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'product': {'type': 'string',
                            'description': 'Product slug (preferred) or name.'},
                'size': {'type': 'string', 'description': 'Size, e.g. "M".'},
                'colour': {'type': 'string', 'description': 'Colour.'},
                'quantity': {'type': 'integer', 'description': 'Quantity 1-10 (default 1).'},
            },
            'required': ['product'],
        },
    },
    {
        'type': 'function',
        'name': 'create_support_request',
        'description': ('Escalate to Modeza support: notify staff about a '
                        'customer issue. Only when the customer asks to '
                        'contact support or the issue cannot be resolved.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string',
                            'description': 'Short summary of the customer issue (no secrets).'},
                'order_number': {'type': 'string',
                                 'description': 'Related order number, if any.'},
            },
            'required': ['message'],
        },
    },
]

HANDLERS = {
    'search_products': search_products,
    'compare_products': compare_products,
    'check_variant_availability': check_variant_availability,
    'get_active_promotions': get_active_promotions,
    'validate_promotion_code': validate_promotion_code,
    'get_order_status': get_order_status,
    'get_customer_orders': get_customer_orders,
    'get_store_policy': get_store_policy,
    'prepare_add_to_cart': prepare_add_to_cart,
    'create_support_request': create_support_request,
}

_MAX_STRING_ARG = 300
_MAX_LIST_ARG = 12


def sanitize_arguments(arguments):
    """Coerce model-provided arguments; models are untrusted input."""
    if not isinstance(arguments, dict):
        return {}
    clean = {}
    for key, value in arguments.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        if isinstance(value, str):
            clean[key] = value.strip()[:_MAX_STRING_ARG]
        elif isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            clean[key] = int(value) if abs(value) < 10 ** 9 else 0
        elif isinstance(value, list):
            clean[key] = [v for v in value[:_MAX_LIST_ARG] if isinstance(v, str)][:_MAX_LIST_ARG]
    return clean


def execute(name, arguments, context):
    """Run one tool call. Returns a :class:`ToolExecution` — never raises."""
    started = time.monotonic()
    args = sanitize_arguments(arguments)
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolExecution(name=name, arguments=args, payload=None,
                             status='error', error_code='unknown_tool',
                             duration_ms=int((time.monotonic() - started) * 1000))
    try:
        payload = handler(context=context, **args)
    except TypeError as exc:
        return ToolExecution(name=name, arguments=args, payload=None,
                             status='error', error_code='bad_arguments',
                             duration_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001 - tool bugs stay inside the turn
        return ToolExecution(name=name, arguments=args, payload=None,
                             status='error', error_code='tool_error',
                             duration_ms=int((time.monotonic() - started) * 1000))
    return ToolExecution(name=name, arguments=args, payload=payload,
                         status='ok', error_code='',
                         duration_ms=int((time.monotonic() - started) * 1000))
