"""Receipt lifecycle services.

Single-writer design mirrors the rest of Modeza:

* :func:`generate_receipt` is the only creation path and is invoked from
  ``payments.services`` the moment a payment succeeds. It is **idempotent**
  (one receipt per order) and **never raises** — a failing receipt must never
  undo a successful payment.
* :func:`regenerate_receipt` re-renders an existing receipt (admin repair path)
  and is allowed to surface errors to the caller.
* :func:`email_receipt` delivers the PDF attachment and never raises.
"""

import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from admin_ui.models import notify_customer
from admin_ui.services import AdminNotificationService
from audit.services import AuditLogService
from emails.services import queue_email

from .models import Receipt
from .pdf import render_receipt_pdf

logger = logging.getLogger('receipts')


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

def next_receipt_number(issued_at=None):
    """Format a receipt number from its local issue date and second."""
    issued_local = timezone.localtime(issued_at or timezone.now())
    return issued_local.strftime('R-%Y%m%d-%H%M%S')


def _next_receipt_issue_time(
        issued_at, *, excluding_receipt_id=None, avoid_number=''):
    """Find an unused second so every receipt number remains unique."""
    from datetime import timedelta

    issued_local = timezone.localtime(issued_at)
    while True:
        number = next_receipt_number(issued_local)
        matches = Receipt.objects.filter(receipt_number=number)
        if excluding_receipt_id is not None:
            matches = matches.exclude(pk=excluding_receipt_id)
        if number != avoid_number and not matches.exists():
            return issued_local
        issued_local += timedelta(seconds=1)


def build_snapshot(order):
    """Freeze the billed customer, line items and totals for the PDF."""
    customer = order.customer or {}
    return {
        'customer': {
            'fullName': customer.get('fullName') or customer.get('full_name') or '',
            'email': customer.get('email') or '',
            'phone': customer.get('phone') or '',
            'addressLine1': customer.get(
                'addressLine1') or customer.get('address_line1') or '',
            'addressLine2': customer.get(
                'addressLine2') or customer.get('address_line2') or '',
            'city': customer.get('city') or '',
            'stateOrProvince': customer.get('county') or customer.get(
                'stateOrProvince') or customer.get('state') or '',
            'postalCode': customer.get('postalCode') or '',
        },
        'items': [
            {
                'product_name': item.product_name,
                'variant_sku': item.variant_sku,
                'variant_size': item.variant_size,
                'variant_color': item.variant_color,
                'image_url': item.image_url,
                'unit_price_minor': item.unit_price_minor,
                'quantity': item.quantity,
                'line_total_minor': item.line_total_minor,
            }
            for item in order.items.all()
        ],
        'subtotal_minor': order.subtotal_minor,
        'discount_minor': getattr(order, 'discount_minor', 0) or 0,
        'shipping_cost_minor': order.shipping_cost_minor,
        'shipping_discount_minor': getattr(order, 'shipping_discount_minor', 0) or 0,
        'coupon_code': getattr(order, 'coupon_code', '') or '',
        'tax_minor': order.tax_minor,
        'total_minor': order.total_minor,
        'shipping_method': order.shipping_method,
        'payment_method': order.payment_method,
        'currency': order.currency or 'KES',
    }


def get_receipt_for_order(order):
    return Receipt.objects.filter(order=order).first()


# ---------------------------------------------------------------------------
# Generation / regeneration
# ---------------------------------------------------------------------------

def generate_receipt(order, *, intent=None):
    """Create (or return) the receipt for a paid order.

    The receipt row may be minted as soon as payment succeeds, but the
    customer only becomes eligible to see, print or download it after the
    order leaves ``pending`` (admin confirmation): customer email and
    notification delivery is deferred until then, and the customer-facing
    endpoints enforce the same rule.

    The operation is idempotent and no-op safe. Any failure is recorded on
    the existing receipt row (status ``failed``) and audited as
    ``receipt_generation_failed`` so the order confirmation itself is never
    affected.
    """
    if order.payment_status != order.PaymentStatus.PAID:
        return Receipt.objects.filter(order=order).first()
    try:
        return _generate_impl(order, intent)
    except Exception:
        logger.exception(
            'Receipt generation failed for order %s.', order.order_number)
        try:
            AuditLogService.log(
                'receipt_generation_failed',
                object_type='order',
                object_id=order.pk,
                object_repr=order.order_number,
                category='payments',
                result='failure',
                severity='high',
                metadata={'order_number': order.order_number},
                description=(
                    f'Receipt generation failed for order {order.order_number}.'),
            )
        except Exception:
            logger.exception('Audit write for failed receipt skipped.')
        return Receipt.objects.filter(order=order).first()


def _generate_impl(order, intent):
    existing = get_receipt_for_order(order)
    if existing is not None and existing.status == Receipt.Status.GENERATED:
        _send_customer_receipt_if_confirmed(existing, order)
        return existing

    gateway_reference = _clean_gateway_reference(order, intent)
    checkout_request_id = _clean_checkout_request_id(intent)

    if existing is None:
        issued_at = _next_receipt_issue_time(timezone.now())
        receipt_number = next_receipt_number(issued_at)
        receipt = Receipt.objects.create(
            order=order,
            receipt_number=receipt_number,
            snapshot=build_snapshot(order),
            amount_minor=order.total_minor,
            currency=order.currency or 'KES',
            gateway_reference=gateway_reference,
            checkout_request_id=checkout_request_id,
        )
    else:
        issued_at = None
        receipt = existing
        receipt.snapshot = build_snapshot(order)
        receipt.amount_minor = order.total_minor
        receipt.currency = order.currency or 'KES'
        if gateway_reference:
            receipt.gateway_reference = gateway_reference
        if checkout_request_id:
            receipt.checkout_request_id = checkout_request_id
        receipt.save(update_fields=[
            'snapshot', 'amount_minor', 'currency',
            'gateway_reference', 'checkout_request_id', 'updated_at'])

    try:
        _render_and_store(receipt, generated_at=issued_at)
    except Exception:
        logger.exception(
            'PDF render/store failed for receipt %s.', receipt.receipt_number)
        note = f'Failed at {timezone.now().isoformat()}'
        Receipt.objects.filter(pk=receipt.pk).update(
            status=Receipt.Status.FAILED, notes=note, updated_at=timezone.now())
        receipt.status = Receipt.Status.FAILED
        receipt.notes = note
        AuditLogService.log(
            'receipt_generation_failed',
            object_type='receipt',
            object_id=receipt.pk,
            object_repr=receipt.receipt_number,
            category='payments',
            result='failure',
            severity='high',
            metadata={'order_number': order.order_number,
                      'step': 'pdf_render'},
            description=f'Receipt {receipt.receipt_number} could not be generated.',
        )
        return receipt

    audit_log = AuditLogService.log(
        'receipt_generated',
        object_type='receipt',
        object_id=receipt.pk,
        object_repr=receipt.receipt_number,
        category='payments',
        metadata={
            'order_number': order.order_number,
            'gateway_reference': receipt.gateway_reference,
            'amount_minor': receipt.amount_minor,
            'pdf_key': receipt.pdf_key,
        },
        description=f'Receipt {receipt.receipt_number} generated for '
        f'order {order.order_number}.',
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'receipt-issued:{order.pk}',
        message=f'Receipt {receipt.receipt_number} issued for '
        f'order {order.order_number}.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    _send_customer_receipt_if_confirmed(receipt, order)
    return receipt


def _send_customer_receipt_if_confirmed(receipt, order):
    """Deliver the receipt to the customer only after admin confirmation.

    The receipt row itself may be minted earlier (e.g. on payment success)
    as the official record, but the customer email, notification and
    download availability wait until the order leaves ``pending`` so a
    customer can never print or download the receipt before an admin
    confirms the order. Idempotent: safe to call on every code path.
    """
    if order.status in (order.Status.PENDING, order.Status.CANCELLED):
        return
    if order.user is not None:
        notify_customer(
            order.user,
            'payment',
            'Receipt available',
            f'Your official receipt {receipt.receipt_number} for order '
            f'{order.order_number} is ready.',
            link=f'/account/orders/{order.order_number}',
            event_key=f'customer-receipt:{order.pk}',
        )

    transaction.on_commit(
        lambda pk=receipt.pk: dispatch_receipt_email(pk))


def regenerate_receipt(receipt):
    """Issue a replacement receipt number and re-render its PDF."""
    order = receipt.order
    previous_receipt_number = receipt.receipt_number
    issued_at = _next_receipt_issue_time(
        timezone.now(), excluding_receipt_id=receipt.pk,
        avoid_number=receipt.receipt_number)
    receipt.receipt_number = next_receipt_number(issued_at)
    receipt.snapshot = build_snapshot(order)
    receipt.amount_minor = order.total_minor
    receipt.currency = order.currency or 'KES'
    receipt = _render_and_store(receipt, generated_at=issued_at)
    audit_log = AuditLogService.log(
        'receipt_regenerated',
        object_type='receipt',
        object_id=receipt.pk,
        object_repr=receipt.receipt_number,
        category='payments',
        metadata={'order_number': order.order_number,
                  'previous_receipt_number': previous_receipt_number,
                  'pdf_key': receipt.pdf_key},
        description=f'Receipt {receipt.receipt_number} regenerated for '
        f'order {order.order_number}.',
    )
    AdminNotificationService.notify_for_audit(
        audit_log,
        event_key=f'receipt-regenerated:{order.pk}',
        message=f'Receipt {receipt.receipt_number} was regenerated for '
        f'order {order.order_number}.',
        link=f'/admin/dashboard/orders/{order.pk}/',
    )
    return receipt


def _render_and_store(receipt, generated_at=None):
    """Render the PDF, persist to storage and record storage metadata."""
    order = receipt.order
    receipt.generated_at = generated_at or timezone.now()
    pdf_bytes = render_receipt_pdf(receipt)
    pdf_key = f'receipts/{order.order_number}/{receipt.receipt_number}.pdf'
    content = ContentFile(pdf_bytes)
    content.content_type = 'application/pdf'
    name = default_storage.save(pdf_key, content)
    receipt.pdf_key = name
    receipt.pdf_url = default_storage.url(name)
    receipt.payload_size = len(pdf_bytes)
    receipt.status = Receipt.Status.GENERATED
    receipt.notes = ''
    receipt.save(update_fields=[
        'receipt_number', 'pdf_key', 'pdf_url', 'payload_size', 'generated_at',
        'status', 'notes', 'updated_at'])
    return receipt


# ---------------------------------------------------------------------------
# Delivery (email)
# ---------------------------------------------------------------------------

def dispatch_receipt_email(receipt_id):
    """Run email delivery after commit. Never raises out of on_commit."""
    try:
        receipt = Receipt.objects.select_related('order').get(pk=receipt_id)
        email_receipt(receipt)
    except Receipt.DoesNotExist:
        pass
    except Exception:
        logger.exception('Receipt email dispatch failed for %s.', receipt_id)


def email_receipt(receipt, *, force=False):
    """Queue the receipt PDF for delivery. Idempotent; never raises.

    Delivery, retries and the ``receipt.email_*`` bookkeeping all live in the
    central email subsystem (see ``emails.hooks``): this function only decides
    *what* to send and records the "no address" case that never reaches SMTP.
    """
    if receipt.email_sent_at and not force:
        return receipt

    order = receipt.order
    customer = receipt.snapshot.get('customer') or {}
    recipient = (customer.get('email') or '').strip()
    if not recipient:
        receipt.email_attempts += 1
        receipt.email_error = 'No customer email on file.'
        receipt.save(update_fields=['email_attempts',
                     'email_error', 'updated_at'])
        return receipt
    if not receipt.pdf_key:
        receipt.email_attempts += 1
        receipt.email_error = 'Receipt PDF has not been generated.'
        receipt.save(update_fields=['email_attempts',
                     'email_error', 'updated_at'])
        return receipt

    subject = (
        f'Your Modeza receipt {receipt.receipt_number} '
        f'for order {order.order_number}')
    body = (
        f'Dear {customer.get("fullName") or "customer"},\n\n'
        f'Thank you for shopping with '
        f'{getattr(settings, "STORE_NAME", "Modeza Boutique")}.\n'
        f'Your official receipt {receipt.receipt_number} for order '
        f'{order.order_number} is attached.\n\n'
        f'Total paid: {receipt.currency} '
        f'{float(receipt.amount_minor or 0) / 100:.2f}\n\n'
        f'If you believe this was sent in error, contact us at '
        f'{getattr(settings, "STORE_EMAIL", "")}.\n\n'
        f'{getattr(settings, "STORE_NAME", "Modeza Boutique")}\n'
        f'{getattr(settings, "STORE_ADDRESS", "")}'
    )
    queue_email(
        email_type='receipt',
        subject=subject,
        body_text=body,
        recipient_email=recipient,
        recipient_name=customer.get('fullName') or '',
        related_user=order.user,
        related_order=order,
        attachments=[{
            'key': receipt.pdf_key,
            'name': f'{receipt.receipt_number}.pdf',
            'mimetype': 'application/pdf',
        }],
        metadata={'receipt_id': str(receipt.pk)},
        notification={
            'category': 'payment',
            'title': 'Receipt available',
            'message': f'Your official receipt {receipt.receipt_number} for '
                       f'order {order.order_number} is ready.',
            'link': f'/account/orders/{order.order_number}',
            'event_key': f'customer-receipt:{order.pk}',
        },
        idempotency_key=(
            f'receipt:order:{order.pk}' if not force
            else f'receipt:order:{order.pk}:force:{uuid.uuid4().hex}'),
        defer=False,
    )
    return receipt


def read_pdf_bytes(receipt):
    """Read the stored PDF for a receipt as raw bytes."""
    if not receipt.pdf_key:
        raise ValueError(
            f'Receipt {receipt.receipt_number} has no stored PDF.')
    with default_storage.open(receipt.pdf_key, 'rb') as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_gateway_reference(order, intent):
    ref = ''
    if intent is not None:
        ref = getattr(intent, 'gateway_reference', '') or ''
    if not ref:
        ref = (order.customer or {}).get('gateway_reference') or ''
    return ref


def _clean_checkout_request_id(intent):
    if intent is None:
        return ''
    return getattr(intent, 'checkout_request_id', '') or ''
