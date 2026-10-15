import uuid

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from admin_ui.models import notify_customer
from admin_ui.services import AdminNotificationService
from audit.services import AuditLogService
from cart.models import Cart
from catalog.models import Product
from emails.services import queue_email
from inventory.services import release_reservation, reserve_variant
from receipts.services import generate_receipt

from .models import Order, OrderItem

FREE_SHIPPING_THRESHOLD_MINOR = 15000
EXPRESS_SHIPPING_COST_MINOR = 1500
VAT_RATE = 0.16


def _audit_order(action, order, result='success', metadata=None, status_code=None):
    return AuditLogService.log(
        action,
        object_type='order',
        object_id=order.pk,
        object_repr=order.order_number,
        category='orders',
        result=result,
        metadata=metadata,
        status_code=status_code,
        description=f'{action}: order {order.order_number}',
    )


def _customer_email(order):
    return ((order.customer or {}).get('email') or '').strip()


def _money(minor):
    return f'{(minor or 0) / 100:.2f}'


def _order_summary(order, headline):
    customer = order.customer or {}
    name = (customer.get('fullName') or '').strip() or 'there'
    quantity = sum(item.quantity for item in order.items.all())
    lines = [
        f'Hi {name},\n\n{headline}\n',
        f'Order number: {order.order_number}\n',
        f'Items: {quantity}\n',
    ]
    if getattr(order, 'discount_minor', 0):
        snapshot = getattr(order, 'promotion_snapshot', None) or {}
        code = getattr(order, 'coupon_code', '') or snapshot.get('coupon_code', '')
        lines.append(f'Promotion ({code}): -{order.currency or "KES"} {_money(order.discount_minor)}\n')
    lines.append(
        f'Total: {order.currency or "KES"} {_money(order.total_minor)}\n'
        f'Shipping: {order.shipping_method}\n'
        f'Payment: {order.payment_method}\n\n'
        f'View your order: '
        f'{getattr(settings, "FRONTEND_ORIGIN", "http://localhost:3000")}'
        f'/account/orders/{order.order_number}\n\n'
        f'{getattr(settings, "STORE_NAME", "MODEZA Boutique")}\n'
        f'{getattr(settings, "STORE_ADDRESS", "")}'
    )
    return ''.join(lines)


def _queue_order_email(email_type, order, subject, headline, notification):
    """Queue the customer email for after the transaction commits.

    ``notification`` is the very same payload the call site just handed to
    ``notify_customer``. Carrying it along means a successful delivery can
    still surface in the storefront if the in-app write ever regresses, while
    the shared ``event_key`` keeps the two from both firing for one event.
    """
    recipient = _customer_email(order)
    if not recipient:
        return None
    return queue_email(
        email_type=email_type,
        subject=subject,
        body_text=_order_summary(order, headline),
        recipient_email=recipient,
        recipient_name=(order.customer or {}).get('fullName') or '',
        related_user=order.user,
        related_order=order,
        notification=notification,
    )


@transaction.atomic
def receive_order(order):
    if order.status == Order.Status.RECEIVED:
        return order
    if order.status != Order.Status.DELIVERED:
        raise ValidationError(
            {'status': 'Only delivered orders can be marked as received.'})

    previous_status = order.status
    order.status = Order.Status.RECEIVED
    order.save(update_fields=['status', 'updated_at'])
    _audit_order(
        'order_received', order,
        metadata={'from': previous_status, 'to': Order.Status.RECEIVED,
                  'reason': 'received'},
    )

    received = {
        'category': 'order',
        'title': 'Order received',
        'message': f'Your order {order.order_number} has been marked as received.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-order-received:{order.pk}',
    }
    if order.user is not None:
        notify_customer(
            order.user,
            received['category'], received['title'], received['message'],
            link=received['link'], event_key=received['event_key'],
        )
    _queue_order_email(
        'order_received', order,
        f'Order {order.order_number} received',
        received['message'], received,
    )

    return order


@transaction.atomic
def mark_received_paid(order):
    # For cash/pay-on-delivery orders the payment is collected at handover, so
    # confirming receipt on a delivered order settles the outstanding balance.
    if order.status == Order.Status.RECEIVED:
        return order
    is_delivery_payment = order.payment_method in {
        'cash_on_delivery',
        'pay_on_delivery',
    }
    # Delivery-payment orders can be settled and marked received at handover
    # even while still pending (the shop may not update the status first).
    receivable_statuses = (
        (Order.Status.PENDING, Order.Status.CONFIRMED, Order.Status.DELIVERED)
        if is_delivery_payment
        else (Order.Status.CONFIRMED, Order.Status.DELIVERED)
    )
    if order.status not in receivable_statuses:
        raise ValidationError(
            {'status': 'Only confirmed or delivered orders can be marked as received and paid.'})

    previous_status = order.status
    previous_payment = order.payment_status
    order.status = Order.Status.RECEIVED
    if is_delivery_payment and order.payment_status != Order.PaymentStatus.PAID:
        order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=['status', 'payment_status', 'updated_at'])
    audit_log = _audit_order(
        'order_received', order,
        metadata={'from': previous_status, 'to': Order.Status.RECEIVED,
                  'payment_from': previous_payment,
                  'payment_to': order.payment_status,
                  'reason': 'received_and_paid'},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-received:{order.pk}',
        message=f'Order {order.order_number} has been marked as received.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )

    settled = {
        'category': 'order',
        'title': 'Order received and paid',
        'message': f'Your order {order.order_number} has been marked as received and settled.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-order-received-paid:{order.pk}',
    }
    if order.user is not None:
        notify_customer(
            order.user,
            settled['category'], settled['title'], settled['message'],
            link=settled['link'], event_key=settled['event_key'],
        )
    _queue_order_email(
        'order_received', order,
        f'Order {order.order_number} received',
        settled['message'], settled,
    )

    return order


def shipping_cost_minor(subtotal_minor, shipping_method):
    # Kenya storefront rule: standard shipping is 20% of the cart subtotal and is
    # free once the subtotal reaches the KSh 15,000 threshold. Express is a flat
    # KSh 1,500 premium regardless of subtotal.
    if subtotal_minor <= 0:
        return 0
    if shipping_method == 'express':
        return EXPRESS_SHIPPING_COST_MINOR
    if subtotal_minor >= FREE_SHIPPING_THRESHOLD_MINOR:
        return 0
    return int(round(subtotal_minor * 0.20))


def tax_cost_minor(subtotal_minor):
    # Kenya standard VAT (16%) applied to the taxable subtotal.
    if subtotal_minor <= 0:
        return 0
    return int(round(subtotal_minor * VAT_RATE))


@transaction.atomic
def create_order(cart_key, payload, user=None):
    try:
        cart = Cart.objects.select_for_update().prefetch_related(
            'items__variant__product').get(cart_key=cart_key)
    except Cart.DoesNotExist as exc:
        raise ValidationError({'cart': 'Cart was not found.'}) from exc
    items = list(cart.items.all())
    if not items:
        raise ValidationError(
            {'cart': 'Cannot create an order from an empty cart.'})

    AuditLogService.log(
        'checkout_started',
        category='orders',
        result='success',
        object_type='cart',
        object_id=cart.cart_key,
        metadata={'item_count': len(items), 'payment_method': payload.get(
            'paymentMethod', 'mpesa')},
        description='Checkout started from cart.',
    )

    # --- Promotion resolution (authoritative, server-side) -----------------
    # Coupon precedence: explicit checkout code > code stored on the cart.
    from promotions.models import Promotion, PromotionRedemption, normalize_coupon_code
    from promotions.services import FRIENDLY, price_cart
    requested_code = normalize_coupon_code(
        payload.get('couponCode') or getattr(cart, 'coupon_code', '') or '')

    order_items = []
    subtotal_minor = 0
    for cart_item in items:
        variant = cart_item.variant
        if (not variant.is_active
                or variant.product.status != Product.Status.ACTIVE
                or not variant.product.category.is_active):
            raise ValidationError(
                {'cart': 'An item in your cart is no longer available.'})
        price_minor = variant.price_minor if variant.price_minor is not None else variant.product.price_minor
        line_total_minor = price_minor * cart_item.quantity
        subtotal_minor += line_total_minor
        order_items.append((cart_item, variant, price_minor, line_total_minor))

    shipping_method = payload.get('shippingMethod', 'standard')
    payment_method = payload.get('paymentMethod', 'mpesa')

    # Lock any coupon promotion row first so concurrent checkouts racing for
    # the final redemption are serialized (usage limits enforced below).
    if requested_code:
        promo_row = Promotion.objects.select_for_update().filter(
            coupon_code_normalized=requested_code).first()
        if promo_row is not None and promo_row.status != Promotion.Status.ACTIVE:
            promo_row = promo_row  # evaluated below for a precise error

    breakdown = price_cart(cart, user=user, shipping_method=shipping_method,
                           coupon_code=requested_code)
    coupon_applied = any(
        normalize_coupon_code(entry.get('code') or '') == requested_code
        for entry in breakdown.get('applied') or []
    )
    if requested_code and not coupon_applied:
        err = breakdown.get('coupon_error') or 'INVALID_CODE'
        from audit.services import AuditLogService as _ALS
        _ALS.log('promotion_redemption_failed', category='orders', result='failure',
                 object_type='promotion', object_repr=requested_code,
                 metadata={'code': err, 'cart_key': cart_key},
                 description=f'Checkout rejected coupon {requested_code}: {err}.')
        raise ValidationError(
            {'couponCode': FRIENDLY.get(err, 'Invalid promotion code.')})
    # Re-check usage limits under the row lock (price_cart counted without it).
    if requested_code:
        for entry in breakdown.get('applied') or []:
            if (entry.get('code') or '').upper() == requested_code:
                prow = Promotion.objects.select_for_update().filter(pk=entry['id']).first()
                if prow is not None:
                    base = PromotionRedemption.objects.filter(
                        promotion=prow, voided=False)
                    if prow.usage_limit is not None and base.count() >= prow.usage_limit:
                        raise ValidationError({'couponCode': FRIENDLY['USAGE_LIMIT_REACHED']})
                    if (prow.usage_limit_per_customer is not None and user is not None
                            and getattr(user, 'is_authenticated', False)):
                        if base.filter(user_id=user.pk).count() >= prow.usage_limit_per_customer:
                            raise ValidationError({'couponCode': FRIENDLY['CUSTOMER_LIMIT_REACHED']})

    discount_minor = breakdown.get('discount', 0)
    shipping_discount_minor = breakdown.get('shipping_discount', 0)
    shipping_minor = breakdown.get('shipping', shipping_cost_minor(subtotal_minor, shipping_method))
    tax_minor = breakdown.get('tax', tax_cost_minor(max(0, subtotal_minor - discount_minor)))
    order = Order.objects.create(
        order_number=f'AT-{uuid.uuid4().hex[:12].upper()}',
        cart=cart,
        user=user,
        customer=payload['customer'],
        notes=payload.get('notes', ''),
        subtotal_minor=subtotal_minor,
        discount_minor=discount_minor,
        shipping_cost_minor=shipping_minor,
        shipping_discount_minor=shipping_discount_minor,
        tax_minor=tax_minor,
        total_minor=(subtotal_minor - discount_minor) + shipping_minor + tax_minor,
        shipping_method=shipping_method,
        payment_method=payment_method,
        coupon_code=requested_code,
        promotion_snapshot={
            'discount': discount_minor,
            'shipping_discount': shipping_discount_minor,
            'coupon_code': requested_code,
            'applied': breakdown.get('applied') or [],
            'subtotal': subtotal_minor,
        },
    )
    # Immutable redemption records (one per applied promotion).
    for entry in breakdown.get('applied') or []:
        PromotionRedemption.objects.create(
            promotion_id=entry['id'], order=order,
            user=user if user is not None and getattr(user, 'is_authenticated', False) else None,
            cart_key=cart_key, coupon_code=entry.get('code') or '',
            discount_minor=entry.get('discount') or 0,
            shipping_discount_minor=entry.get('shipping_discount') or 0,
        )
    if breakdown.get('applied'):
        AuditLogService.log(
            'promotion_redeemed', category='orders', object_type='order',
            object_id=order.pk, object_repr=order.order_number,
            metadata={'coupon_code': requested_code, 'discount_minor': discount_minor,
                      'promotions': [e.get('name') for e in breakdown.get('applied') or []]},
            description=f'Promotion redeemed on order {order.order_number}.',
        )
    for cart_item, variant, price_minor, line_total_minor in order_items:
        reserve_variant(order, variant, cart_item.quantity)
        OrderItem.objects.create(
            order=order,
            product=variant.product,
            variant=variant,
            product_name=variant.product.name,
            variant_sku=variant.sku,
            variant_size=variant.size,
            variant_color=variant.color,
            image_url=(variant.product.images or [''])[0],
            unit_price_minor=price_minor,
            quantity=cart_item.quantity,
            line_total_minor=line_total_minor,
        )
    cart.items.all().delete()
    if getattr(cart, 'coupon_code', ''):
        cart.coupon_code = ''
        cart.save(update_fields=['coupon_code', 'updated_at'])
    audit_log = _audit_order(
        'order_created', order,
        status_code=201,
        metadata={'total_minor': order.total_minor,
                  'payment_method': order.payment_method},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-created:{order.pk}',
        message=f'New order {order.order_number} was placed '
        f'({order.customer.get("fullName") or "a customer"}).',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    placed = {
        'category': 'order',
        'title': 'Order placed',
        'message': f'Your order {order.order_number} has been placed and is being prepared.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-order-created:{order.pk}',
    }
    if user is not None:
        notify_customer(
            user,
            placed['category'], placed['title'], placed['message'],
            link=placed['link'], event_key=placed['event_key'],
        )
    _queue_order_email(
        'order_confirmation', order,
        f'Order {order.order_number} received',
        placed['message'], placed,
    )
    return order


@transaction.atomic
def approve_order(order):
    is_delivery_payment = order.payment_method in {
        'cash_on_delivery',
        'pay_on_delivery',
    }
    if order.payment_status != Order.PaymentStatus.PAID and not is_delivery_payment:
        raise ValidationError(
            {'payment_status': 'Only paid orders can be approved.'})
    if order.status == Order.Status.CONFIRMED:
        if order.payment_status == Order.PaymentStatus.PAID:
            generate_receipt(order)
        return order
    previous_status = order.status
    if order.payment_status != Order.PaymentStatus.PAID and is_delivery_payment:
        order.payment_status = Order.PaymentStatus.PAID
    order.status = Order.Status.CONFIRMED
    order.save(update_fields=['status', 'payment_status', 'updated_at'])
    audit_log = _audit_order(
        'order_confirmed', order,
        metadata={'from': previous_status, 'to': Order.Status.CONFIRMED,
                  'reason': 'approved'},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-confirmed:{order.pk}',
        message=f'Order {order.order_number} has been confirmed.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    confirmed = {
        'category': 'order',
        'title': 'Order confirmed',
        'message': f'Your order {order.order_number} has been confirmed and is now being prepared.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-order-confirmed:{order.pk}',
    }
    if order.user is not None:
        notify_customer(
            order.user,
            confirmed['category'], confirmed['title'], confirmed['message'],
            link=confirmed['link'], event_key=confirmed['event_key'],
        )
    _queue_order_email(
        'order_confirmed', order,
        f'Order {order.order_number} confirmed',
        confirmed['message'], confirmed,
    )
    generate_receipt(order)
    return order


@transaction.atomic
def refund_order(order):
    if order.payment_status == Order.PaymentStatus.REFUNDED:
        return order
    order.payment_status = Order.PaymentStatus.REFUNDED
    order.save(update_fields=['payment_status', 'updated_at'])
    audit_log = _audit_order(
        'refund_completed', order,
        metadata={'to_payment_status': Order.PaymentStatus.REFUNDED},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-refunded:{order.pk}',
        message=f'Order {order.order_number} was refunded.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    if order.user is not None:
        notify_customer(
            order.user,
            'payment',
            'Refund processed',
            f'Your refund for order {order.order_number} has been processed.',
            link=f'/account/orders/{order.order_number}',
            event_key=f'customer-order-refunded:{order.pk}',
        )
    return order


@transaction.atomic
def request_refund(order, reason=''):
    """Customer-initiated return/refund request for a received order.

    The request is recorded in the authoritative audit trail (real event, no
    invented state) and surfaces as an admin notification. Actual payment
    reversal remains a staff action via :func:`refund_order`.
    """
    if order.payment_status == Order.PaymentStatus.REFUNDED:
        return order
    if order.status not in (Order.Status.RECEIVED, Order.Status.DELIVERED):
        raise ValidationError(
            {'status': 'Only received or delivered orders can request a refund.'})
    audit_log = _audit_order(
        'refund_requested', order,
        metadata={'reason': reason[:500]},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-refund-requested:{order.pk}',
        message=f'Customer requested a refund for order {order.order_number}.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    if order.user is not None:
        notify_customer(
            order.user,
            'payment',
            'Return/refund requested',
            f'We received your refund request for order {order.order_number}.',
            link=f'/account/orders/{order.order_number}',
            event_key=f'customer-order-refund-requested:{order.pk}',
        )
    return order


@transaction.atomic
def cancel_order(order):
    if order.status == Order.Status.CANCELLED:
        return order
    if order.status not in (Order.Status.PENDING, Order.Status.CONFIRMED):
        raise ValidationError(
            {'status': 'Only pending or confirmed orders can be cancelled.'})

    for reservation in order.reservations.select_for_update().all():
        release_reservation(reservation)

    # Void redemptions so cancelled orders free up usage limits while the
    # immutable record (and the order snapshot) remains for history.
    order.promo_redemptions.filter(voided=False).update(voided=True)

    if order.payment_status == Order.PaymentStatus.PAID:
        order.payment_status = Order.PaymentStatus.REFUNDED

    previous_status = order.status
    order.status = Order.Status.CANCELLED
    order.save(update_fields=['status', 'payment_status', 'updated_at'])
    audit_log = _audit_order(
        'order_cancelled', order,
        metadata={'from': previous_status, 'to': Order.Status.CANCELLED,
                  'reason': 'cancelled'},
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'order-cancelled:{order.pk}',
        message=f'Order {order.order_number} was cancelled.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    cancelled = {
        'category': 'order',
        'title': 'Order cancelled',
        'message': f'Your order {order.order_number} has been cancelled.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-order-cancelled:{order.pk}',
    }
    if order.user is not None:
        notify_customer(
            order.user,
            cancelled['category'], cancelled['title'], cancelled['message'],
            link=cancelled['link'], event_key=cancelled['event_key'],
        )
    _queue_order_email(
        'order_cancelled', order,
        f'Order {order.order_number} cancelled',
        cancelled['message'], cancelled,
    )
    return order
