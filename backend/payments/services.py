import secrets
import uuid

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from django.utils import timezone

from admin_ui.models import notify_customer
from admin_ui.services import AdminNotificationService
from audit.services import AuditLogService
from emails.services import queue_email
from inventory.models import StockReservation
from orders.models import Order
from receipts.services import generate_receipt

from .models import PaymentEvent, PaymentIntent
from .daraja import DarajaError, initiate_stk_push, normalize_ke_phone, query_stk_status


def get_order_for_cart(order_number, cart_key, user=None):
    try:
        order = Order.objects.select_related(
            'cart').get(order_number=order_number)
    except Order.DoesNotExist as exc:
        raise NotFound('Order was not found.') from exc
    if user is not None and user.is_authenticated:
        allowed = order.user_id == user.pk
    else:
        allowed = bool(
            order.user_id is None and order.cart and order.cart.user_id is None
            and cart_key and order.cart.cart_key == cart_key)
    if not allowed:
        raise PermissionDenied('You cannot access this order.')
    return order


def _customer_email(order):
    return ((order.customer or {}).get('email') or '').strip()


def _payment_body(order, headline, reference=''):
    customer = order.customer or {}
    name = (customer.get('fullName') or '').strip() or 'there'
    lines = [
        f'Hi {name},',
        '',
        headline,
        '',
        f'Order number: {order.order_number}',
        f'Total: {order.currency or "KES"} {(order.total_minor or 0) / 100:.2f}',
    ]
    if reference:
        lines.append(f'Reference: {reference}')
    lines.extend([
        '',
        'View your order: '
        f'{getattr(settings, "FRONTEND_ORIGIN", "http://localhost:3000")}'
        f'/account/orders/{order.order_number}',
        '',
        getattr(settings, 'STORE_NAME', 'MODEZA Boutique'),
        getattr(settings, 'STORE_ADDRESS', ''),
    ])
    return '\n'.join(lines)


def _queue_payment_email(email_type, order, subject, body_text, notification):
    """Queue a payment-related customer email after the transaction commits.

    ``notification`` is the payload the call site just passed to
    ``notify_customer``; the shared ``event_key`` keeps the two in step.
    """
    recipient = _customer_email(order)
    if not recipient:
        return None
    return queue_email(
        email_type=email_type,
        subject=subject,
        body_text=body_text,
        recipient_email=recipient,
        recipient_name=(order.customer or {}).get('fullName') or '',
        related_user=order.user,
        related_order=order,
        notification=notification,
    )


def create_intent(order_number, method, phone_number, cart_key, user=None):
    order = get_order_for_cart(order_number, cart_key, user)
    try:
        phone = normalize_ke_phone(phone_number or (order.customer or {}).get('phone', ''))
    except DarajaError as exc:
        raise ValidationError({'phoneNumber': exc.message}) from exc
    if method != PaymentIntent.Method.MPESA:
        raise ValidationError({'method': 'Only M-Pesa checkout is currently supported.'})
    # Serialize order retries, then release the lock before the network call.
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status == Order.PaymentStatus.PAID:
            raise ValidationError({'order': 'Order is already paid.'})
        if order.status == Order.Status.CANCELLED:
            raise ValidationError({'order': 'Order was cancelled and cannot be paid.'})
        existing = PaymentIntent.objects.filter(order=order, status=PaymentIntent.Status.PENDING).first()
        if existing:
            return existing
        intent = PaymentIntent.objects.create(
            id=f'pi_{uuid.uuid4().hex}', order=order, amount_minor=order.total_minor,
            currency='KES', method=method,
            metadata={'phoneLast4': phone[-4:]},
        )
        order.payment_intent_id = intent.id
        order.save(update_fields=['payment_intent_id', 'updated_at'])
    AuditLogService.log(
        'payment_initiated', object_type='payment_intent', object_id=intent.id,
        object_repr=order.order_number, category='payments',
        metadata={'method': method, 'order_number': order.order_number}, status_code=201,
        description=f'Payment initiated for order {order.order_number}.',
    )
    try:
        response = initiate_stk_push(phone, intent.amount_minor, order.order_number,
                                     f'MODEZA {order.order_number}')
    except Exception as exc:
        code = exc.code if isinstance(exc, DarajaError) else 'CONFIGURATION_ERROR'
        message = exc.message if isinstance(exc, DarajaError) else 'M-Pesa is not configured. Contact support.'
        intent.status = PaymentIntent.Status.FAILED
        intent.failure_code, intent.failure_message = code, message
        intent.save(update_fields=['status', 'failure_code', 'failure_message', 'updated_at'])
        raise ValidationError({'payment': message}) from exc
    intent.merchant_request_id = response.get('MerchantRequestID', '')
    intent.checkout_request_id = response['CheckoutRequestID']
    intent.initiated_at = timezone.now()
    intent.save(update_fields=['merchant_request_id', 'checkout_request_id', 'initiated_at', 'updated_at'])
    return intent


@transaction.atomic
def _mark_intent_succeeded(intent, gateway_reference):
    if intent.status != PaymentIntent.Status.PENDING:
        return intent.order
    intent.status = PaymentIntent.Status.SUCCEEDED
    intent.gateway_reference = gateway_reference or f'TXN-{uuid.uuid4().hex[:12].upper()}'
    intent.confirmed_at = timezone.now()
    intent.save(update_fields=['status', 'gateway_reference', 'confirmed_at', 'updated_at'])
    order = intent.order
    if order.status == Order.Status.CANCELLED:
        # A payment arriving after cancellation must not revive the order.
        return order
    if order.payment_status == Order.PaymentStatus.PAID:
        # Idempotency: the same intent may be confirmed by both the customer
        # flow and the provider webhook; never duplicate side effects.
        return order
    StockReservation.objects.filter(order=order, status=StockReservation.Status.ACTIVE).update(
        status=StockReservation.Status.COMMITTED)
    order.payment_status = Order.PaymentStatus.PAID
    order.save(update_fields=['payment_status', 'updated_at'])
    # A successful online payment settles the order. The official receipt row
    # is minted now (idempotent; a failing receipt never reverts payment),
    # but customer delivery (email, notification, download) waits until an
    # admin confirms the order.
    generate_receipt(order, intent=intent)
    audit_log = AuditLogService.log(
        'payment_success',
        object_type='order',
        object_id=order.pk,
        object_repr=order.order_number,
        category='payments',
        result='success',
        metadata={'gateway_reference': intent.gateway_reference},
        description=f'Payment succeeded for order {order.order_number}.',
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'payment-success:{order.pk}',
        message=f'Payment received for order {order.order_number}.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    paid = {
        'category': 'payment',
        'title': 'Payment received',
        'message': f'Payment for order {order.order_number} was successful.',
        'link': f'/account/orders/{order.order_number}',
        'event_key': f'customer-payment-success:{order.pk}',
    }
    if order.user is not None:
        notify_customer(
            order.user,
            paid['category'], paid['title'], paid['message'],
            link=paid['link'], event_key=paid['event_key'],
        )
    _queue_payment_email(
        'payment_success', order,
        f'Payment received for order {order.order_number}',
        _payment_body(
            order,
            f'Your payment for order {order.order_number} was received '
            'successfully.',
            intent.gateway_reference,
        ),
        paid,
    )
    return order


@transaction.atomic
def confirm_payment(order_number, payment_intent_id, gateway_reference, cart_key, user=None):
    order = get_order_for_cart(order_number, cart_key, user)
    if order.status == Order.Status.CANCELLED:
        raise ValidationError(
            {'order': 'Order was cancelled and cannot be paid.'})
    try:
        intent = PaymentIntent.objects.select_for_update().get(id=payment_intent_id)
    except PaymentIntent.DoesNotExist as exc:
        raise NotFound('Payment intent was not found.') from exc
    if intent.order_id != order.id:
        raise ValidationError(
            {'paymentIntentId': 'Payment intent does not belong to this order.'})
    if intent.status == PaymentIntent.Status.SUCCEEDED:
        return order
    if intent.status == PaymentIntent.Status.FAILED:
        raise ValidationError(
            {'paymentIntentId': 'Payment intent has failed.'})
    raise ValidationError(
        {'paymentIntentId': 'Payment is still pending provider confirmation.'})


@transaction.atomic
def process_webhook(payload, signature, event_id):
    if not signature or not secrets.compare_digest(signature, settings.PAYMENT_WEBHOOK_SECRET):
        raise PermissionDenied('Invalid webhook signature.')
    event, data = payload.get('event'), payload.get('data', {})
    if not event_id:
        raise ValidationError({'eventId': 'Webhook event ID is required.'})
    # Atomic duplicate suppression: the unique event_id constraint guarantees
    # the first writer wins even under concurrent replays. A replay is
    # acknowledged as a duplicate but side effects stay idempotent so the
    # single authoritative outcome survives retries.
    event_obj, created = PaymentEvent.objects.get_or_create(
        event_id=event_id,
        defaults={'event_type': event or 'unknown', 'payload': payload},
    )
    if created and event_obj.payment_intent_id is None:
        intent_id = data.get('paymentIntentId')
        intent = PaymentIntent.objects.filter(
            id=intent_id).first() if intent_id else None
        if intent:
            event_obj.payment_intent = intent
            event_obj.save(update_fields=['payment_intent'])
    intent = event_obj.payment_intent
    if event in ('payment_intent.succeeded', 'mpesa.stk_callback.success') and intent:
        order = _mark_intent_succeeded(intent, data.get('transactionId', ''))
        return {'received': True, 'status': 'order_marked_paid', 'orderNumber': order.order_number}
    if event in ('payment_intent.payment_failed', 'mpesa.stk_callback.failed') and intent:
        order = intent.order
        if order.status == Order.Status.CANCELLED or order.payment_status == Order.PaymentStatus.PAID:
            return {'received': True, 'status': 'duplicate'}
        if not created:
            return {'received': True, 'status': 'duplicate'}
        intent.status = PaymentIntent.Status.FAILED
        intent.save(update_fields=['status', 'updated_at'])
        audit_log = AuditLogService.log(
            'payment_timeout',
            object_type='order',
            object_id=order.pk,
            object_repr=order.order_number,
            category='payments',
            result='failure',
            metadata={'event': event, 'payment_intent_id': intent.id},
            description=f'Payment timed out for order {order.order_number}.',
        )
        AdminNotificationService.notify_for_audit(
            audit_log,
            event_key=f'payment-timeout:{order.pk}',
            message=f'Payment for order {order.order_number} did not complete.',
            link=f'/admin/dashboard/orders/{order.pk}/',
        )
        failed = {
            'category': 'payment',
            'title': 'Payment failed',
            'message': f'Payment for order {order.order_number} did not complete. You can try again.',
            'link': f'/account/orders/{order.order_number}',
            'event_key': f'customer-payment-failed:{order.pk}',
        }
        if order.user is not None:
            notify_customer(
                order.user,
                failed['category'], failed['title'], failed['message'],
                link=failed['link'], event_key=failed['event_key'],
            )
        _queue_payment_email(
            'payment_failed', order,
            f'Payment failed for order {order.order_number}',
            _payment_body(
                order,
                'Your payment did not complete and no charge was made. '
                'You can try again whenever you are ready.',
            ),
            failed,
        )
        return {'received': True, 'status': 'payment_failed', 'orderNumber': order.order_number}
    return {'received': True, 'status': 'unhandled_event'}
