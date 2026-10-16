"""Deterministic server-side promotion engine.

Priority / stacking contract (documented behaviour):
  1. Collect eligible promotions (date window, status, min order/qty,
     targeting, customer scope, usage limits).
  2. Sort by (-priority, name, pk) for determinism.
  3. If any eligible promotion is non-stackable, only the single
     highest-priority non-stackable promotion applies (coupon promos beat
     automatic ones on exact priority ties when a coupon was supplied).
  4. Otherwise all eligible stackable promotions apply; merchandise
     discounts are capped so they never exceed the eligible subtotal and
     shipping discounts never exceed the shipping charge.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from .models import Promotion, PromotionRedemption, normalize_coupon_code

# Canonical coupon validation error codes (stable API contract).
ERR_INVALID = 'INVALID_CODE'
ERR_NOT_STARTED = 'NOT_STARTED'
ERR_EXPIRED = 'EXPIRED'
ERR_DISABLED = 'NOT_AVAILABLE'
ERR_USAGE_LIMIT = 'USAGE_LIMIT_REACHED'
ERR_CUSTOMER_LIMIT = 'CUSTOMER_LIMIT_REACHED'
ERR_CUSTOMER = 'NOT_AVAILABLE_FOR_CUSTOMER'
ERR_MIN_ORDER = 'MINIMUM_ORDER_NOT_REACHED'
ERR_MIN_QTY = 'MINIMUM_QUANTITY_NOT_REACHED'
ERR_NO_ITEMS = 'DOES_NOT_APPLY_TO_CART'

FRIENDLY = {
    ERR_INVALID: 'Invalid promotion code.',
    ERR_NOT_STARTED: 'This promotion has not started yet.',
    ERR_EXPIRED: 'This promotion has expired.',
    ERR_DISABLED: 'This promotion is not available.',
    ERR_USAGE_LIMIT: 'This promotion has reached its usage limit.',
    ERR_CUSTOMER_LIMIT: 'You have already used this promotion.',
    ERR_CUSTOMER: 'This promotion is not available for your account.',
    ERR_MIN_ORDER: 'Minimum order value not reached for this promotion.',
    ERR_MIN_QTY: 'Minimum quantity not reached for this promotion.',
    ERR_NO_ITEMS: 'This promotion does not apply to items in your cart.',
}


def _pct(amount_minor, percent):
    return int((Decimal(amount_minor) * Decimal(percent) / Decimal(100)).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP))


def _line_price(variant, product):
    if getattr(variant, 'price_minor', None) is not None:
        return variant.price_minor
    return product.price_minor


def cart_lines(cart):
    """Return enriched line dicts for a cart (prefetched by caller ideally)."""
    lines = []
    for item in cart.items.select_related('variant__product__category').all():
        variant = item.variant
        product = variant.product
        price = _line_price(variant, product)
        lines.append({
            'item': item,
            'variant': variant,
            'product': product,
            'category_id': product.category_id,
            'quantity': item.quantity,
            'unit_price': price,
            'line_total': price * item.quantity,
            'is_sale': (product.compare_at_price_minor or 0) > price,
            'is_new': bool(getattr(product, 'is_new_arrival', False)),
        })
    return lines


def _target_sets(promo):
    if getattr(promo, '_prefetched', False):
        return promo
    # Attach cached id sets to avoid N+1 in the engine loop.
    promo._product_ids = set(promo.promo_products.values_list('product_id', flat=True))
    promo._category_ids = set(promo.promo_categories.values_list('category_id', flat=True))
    promo._variant_ids = set(promo.promo_variants.values_list('variant_id', flat=True))
    promo._prefetched = True
    return promo


def line_eligible(promo, line):
    promo = _target_sets(promo)
    if promo.eligible_all and not promo.sale_only and not promo.new_only:
        scoped = True
    else:
        scoped = False
        if promo.eligible_all:
            scoped = True
        if line['variant'].id in promo._variant_ids:
            scoped = True
        if line['product'].id in promo._product_ids:
            scoped = True
        if line['category_id'] in promo._category_ids:
            scoped = True
        if not scoped:
            return False
    if promo.sale_only and not line['is_sale']:
        return False
    if promo.new_only and not line['is_new']:
        return False
    return True


def eligible_subtotal(promo, lines):
    return sum(1 for _ in ())  # placeholder replaced below


def eligible_lines(promo, lines):
    return [line for line in lines if line_eligible(promo, line)]


def _customer_order_count(user):
    if user is None or getattr(user, 'is_anonymous', False):
        return 0
    from orders.models import Order
    return Order.objects.filter(user_id=user.pk).exclude(status='cancelled').count()


def check_customer_scope(promo, user):
    scope = promo.customer_scope or Promotion.CustomerScope.ALL
    if scope == Promotion.CustomerScope.ALL:
        return True, ''
    if user is None or getattr(user, 'is_anonymous', False):
        # Guests count as new customers.
        return (True, '') if scope in (Promotion.CustomerScope.ALL, Promotion.CustomerScope.NEW) else (False, ERR_CUSTOMER)
    if scope == Promotion.CustomerScope.SPECIFIC:
        if promo.promo_customers.filter(user_id=user.pk).exists():
            return True, ''
        return False, ERR_CUSTOMER
    count = _customer_order_count(user)
    if scope == Promotion.CustomerScope.NEW:
        return (True, '') if count == 0 else (False, ERR_CUSTOMER)
    if scope == Promotion.CustomerScope.EXISTING:
        return (True, '') if count > 0 else (False, ERR_CUSTOMER)
    return True, ''


def check_usage_limits(promo, user):
    base = PromotionRedemption.objects.filter(promotion_id=promo.pk, voided=False)
    if promo.usage_limit is not None and base.count() >= promo.usage_limit:
        return False, ERR_USAGE_LIMIT
    if promo.usage_limit_per_customer is not None and user is not None and not getattr(user, 'is_anonymous', False):
        mine = base.filter(user_id=user.pk).count()
        if mine >= promo.usage_limit_per_customer:
            return False, ERR_CUSTOMER_LIMIT
    return True, ''


def evaluate_promotion(promo, lines, subtotal_minor, total_qty, user, now=None):
    """Return (ok, code, discount_minor, shipping_discount_minor, eligible_sub)."""
    now = now or timezone.now()
    if promo.status != Promotion.Status.ACTIVE:
        return False, ERR_DISABLED, 0, 0, 0
    if promo.starts_at and now < promo.starts_at:
        return False, ERR_NOT_STARTED, 0, 0, 0
    if promo.ends_at and now > promo.ends_at:
        return False, ERR_EXPIRED, 0, 0, 0
    if subtotal_minor < (promo.minimum_order_value_minor or 0):
        return False, ERR_MIN_ORDER, 0, 0, 0
    if total_qty < (promo.minimum_quantity or 0):
        return False, ERR_MIN_QTY, 0, 0, 0
    ok, code = check_customer_scope(promo, user)
    if not ok:
        return False, code, 0, 0, 0
    ok, code = check_usage_limits(promo, user)
    if not ok:
        return False, code, 0, 0, 0

    elines = eligible_lines(promo, lines)
    if not elines:
        return False, ERR_NO_ITEMS, 0, 0, 0
    eligible_sub = sum(line['line_total'] for line in elines)
    if eligible_sub <= 0:
        return False, ERR_NO_ITEMS, 0, 0, 0

    ptype = promo.promotion_type
    if ptype == Promotion.Type.PERCENTAGE:
        discount = _pct(eligible_sub, promo.discount_percent or 0)
        if promo.maximum_discount_minor is not None:
            discount = min(discount, promo.maximum_discount_minor)
        return True, '', min(discount, eligible_sub), 0, eligible_sub
    if ptype == Promotion.Type.FIXED:
        discount = min(promo.discount_amount_minor or 0, eligible_sub)
        return True, '', discount, 0, eligible_sub
    if ptype == Promotion.Type.FREE_SHIPPING:
        # Shipping discount resolved by caller against the shipping charge.
        return True, '', 0, -1, eligible_sub
    if ptype == Promotion.Type.BUY_X_GET_Y:
        return _evaluate_bxgy(promo, elines, eligible_sub, free=True)
    if ptype == Promotion.Type.BUY_X_GET_PCT:
        return _evaluate_bxgy(promo, elines, eligible_sub, free=False)
    return False, ERR_DISABLED, 0, 0, 0


def _evaluate_bxgy(promo, elines, eligible_sub, free=True):
    q = promo.qualifying_quantity or 0
    r = promo.reward_quantity or 0
    if q <= 0 or r <= 0:
        return False, ERR_DISABLED, 0, 0, eligible_sub
    # Expand units cheapest-first for deterministic "cheapest free" behaviour.
    units = []
    for line in elines:
        units.extend([line['unit_price']] * line['quantity'])
    units.sort()
    group = q + r
    full_groups = len(units) // group
    if promo.max_redemptions_per_order is not None:
        full_groups = min(full_groups, promo.max_redemptions_per_order)
    if full_groups <= 0:
        return False, ERR_NO_ITEMS, 0, 0, eligible_sub
    # Cheapest `r` units of each group are free — with a globally sorted list
    # the first full_groups*r units are exactly those.
    free_units = units[:full_groups * r]
    if free:
        discount = sum(free_units)
    else:
        discount = _pct(sum(free_units), promo.reward_discount_percent or 0)
    return True, '', min(discount, eligible_sub), 0, eligible_sub


def candidate_promotions(now=None, coupon_normalized=''):
    now = now or timezone.now()
    qs = Promotion.objects.filter(status=Promotion.Status.ACTIVE)
    qs = qs.filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
    qs = qs.filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
    qs = qs.prefetch_related('promo_products', 'promo_categories', 'promo_variants', 'promo_customers')
    promos = list(qs)
    for promo in promos:
        promo._product_ids = {link.product_id for link in promo.promo_products.all()}
        promo._category_ids = {link.category_id for link in promo.promo_categories.all()}
        promo._variant_ids = {link.variant_id for link in promo.promo_variants.all()}
        promo._prefetched = True
    if coupon_normalized:
        # Coupon promos are matched separately; automatics always included.
        result = [p for p in promos if p.is_automatic or p.coupon_code_normalized == coupon_normalized]
        # Include a disabled/expired coupon target for a precise error: fetch
        # by code regardless of status window when nothing matched.
        if not any(p.coupon_code_normalized == coupon_normalized for p in result):
            extra = Promotion.objects.filter(coupon_code_normalized=coupon_normalized).prefetch_related(
                'promo_products', 'promo_categories', 'promo_variants', 'promo_customers').first()
            if extra is not None:
                extra._product_ids = {link.product_id for link in extra.promo_products.all()}
                extra._category_ids = {link.category_id for link in extra.promo_categories.all()}
                extra._variant_ids = {link.variant_id for link in extra.promo_variants.all()}
                extra._prefetched = True
                result.append(extra)
        return result
    return [p for p in promos if p.is_automatic]


def _shipping_cost(subtotal_minor, shipping_method):
    from orders.services import shipping_cost_minor
    return shipping_cost_minor(subtotal_minor, shipping_method)


def _tax_cost(taxable_minor):
    from orders.services import tax_cost_minor
    return tax_cost_minor(taxable_minor)


def resolve_stacking(evaluated, coupon_normalized=''):
    """Apply priority/stacking contract. ``evaluated`` items are dicts with
    keys: promo, discount, shipping_discount, eligible_sub."""
    if not evaluated:
        return []
    evaluated = sorted(evaluated, key=lambda e: (-e['promo'].priority, e['promo'].name, str(e['promo'].pk)))
    non_stackable = [e for e in evaluated if not e['promo'].stackable]
    if non_stackable:
        top_priority = non_stackable[0]['promo'].priority
        contenders = [e for e in non_stackable if e['promo'].priority == top_priority]
        if len(contenders) > 1 and coupon_normalized:
            coupon_hit = [e for e in contenders if e['promo'].coupon_code_normalized == coupon_normalized]
            if coupon_hit:
                return [coupon_hit[0]]
        return [contenders[0]]
    return evaluated


def price_cart(cart, user=None, shipping_method='standard', coupon_code='', now=None):
    """Authoritative cart pricing. Returns a breakdown dict (minor units)."""
    from orders.services import shipping_cost_minor, tax_cost_minor  # noqa: F401 (keeps constants aligned)
    now = now or timezone.now()
    lines = cart_lines(cart)
    subtotal = sum(line['line_total'] for line in lines)
    total_qty = sum(line['quantity'] for line in lines)
    coupon_normalized = normalize_coupon_code(coupon_code)

    breakdown = {
        'subtotal': subtotal,
        'eligible_subtotal': 0,
        'discount': 0,
        'shipping': 0,
        'shipping_discount': 0,
        'tax': 0,
        'total': 0,
        'applied': [],
        'coupon_error': '',
    }
    if not lines:
        return breakdown

    candidates = candidate_promotions(now=now, coupon_normalized=coupon_normalized)
    evaluated = []
    coupon_found = False
    coupon_error = ''
    for promo in candidates:
        if promo.coupon_code_normalized and promo.coupon_code_normalized == coupon_normalized:
            coupon_found = True
        if not promo.is_automatic and promo.coupon_code_normalized != coupon_normalized:
            continue
        ok, code, discount, ship_disc, eligible_sub = evaluate_promotion(
            promo, lines, subtotal, total_qty, user, now=now)
        if promo.coupon_code_normalized and promo.coupon_code_normalized == coupon_normalized and not ok:
            coupon_error = code
            continue
        if ok:
            evaluated.append({
                'promo': promo, 'discount': discount,
                'shipping_discount': ship_disc, 'eligible_sub': eligible_sub,
            })

    if coupon_normalized and not coupon_found:
        breakdown['coupon_error'] = ERR_INVALID
        candidates_shipping_base = subtotal
    else:
        breakdown['coupon_error'] = coupon_error

    applied = resolve_stacking(evaluated, coupon_normalized=coupon_normalized)

    discount_total = sum(a['discount'] for a in applied)
    discount_total = min(discount_total, subtotal)
    taxable = subtotal - discount_total

    base_shipping = _shipping_cost(subtotal, shipping_method)
    shipping_discount = 0
    if any(a['shipping_discount'] == -1 for a in applied):
        # Free-shipping promo removes the eligible shipping charge entirely.
        shipping_discount = base_shipping
    shipping = max(0, base_shipping - shipping_discount)
    tax = _tax_cost(taxable)
    total = taxable + shipping + tax

    breakdown.update({
        'eligible_subtotal': sum(a['eligible_sub'] for a in applied),
        'discount': discount_total,
        'shipping': shipping,
        'shipping_discount': shipping_discount,
        'tax': tax,
        'total': total,
        'applied': [
            {
                'id': str(a['promo'].pk),
                'name': a['promo'].name,
                # Automatic promotions are evaluated for every eligible order;
                # they must never masquerade as a customer-entered coupon.
                'code': '' if a['promo'].is_automatic else (a['promo'].coupon_code or ''),
                'type': a['promo'].promotion_type,
                'discount': a['discount'] if a['shipping_discount'] != -1 else 0,
                'shipping_discount': base_shipping if a['shipping_discount'] == -1 else 0,
                'eligible_subtotal': a['eligible_sub'],
            }
            for a in applied
        ],
    })
    return breakdown


def validate_coupon(code, cart, user=None, shipping_method='standard'):
    """Validate a single coupon against a cart; returns (breakdown, error)."""
    normalized = normalize_coupon_code(code)
    if not normalized:
        return None, ERR_INVALID
    breakdown = price_cart(cart, user=user, shipping_method=shipping_method, coupon_code=normalized)
    matched = [a for a in breakdown['applied'] if (a['code'] or '').upper() == normalized]
    if matched:
        return breakdown, ''
    return breakdown, breakdown.get('coupon_error') or ERR_INVALID
