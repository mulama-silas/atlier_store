import logging

from django.http import FileResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffOrAdmin
from audit.services import AuditLogService
from orders.models import Order
from orders.views import can_access_order

from .models import Receipt
from .serializers import ReceiptSerializer
from .services import read_pdf_bytes, regenerate_receipt

logger = logging.getLogger('receipts')


def _cart_key(request):
    return request.headers.get('x-cart-id')


def _can_access_order(request, order):
    """Use the same strict account or guest ownership rule as order APIs."""
    return can_access_order(request, order)


# Order states in which the customer may see, print or download the
# receipt. A receipt becomes available only once an admin confirms the
# order (``confirmed`` and every later fulfilment state). ``pending``
# (awaiting approval) and ``cancelled`` orders never expose it.
_RECEIPT_VISIBLE_STATUSES = frozenset({
    Order.Status.CONFIRMED,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
    Order.Status.RECEIVED,
})


def _order_receipt_visible(order):
    return order.status in _RECEIPT_VISIBLE_STATUSES


def _not_ready_error():
    return _error(
        'RECEIPT_NOT_READY',
        'The receipt will be available once an admin confirms your order.',
        403)


def _error(code, message, status):
    return Response(
        {'error': {'code': code, 'message': message, 'details': {}}},
        status=status)


def _receipt_or_404(receipt_number):
    receipt = Receipt.objects.select_related(
        'order__cart', 'order__user').filter(
        receipt_number=receipt_number).first()
    if receipt is None:
        return None, _error(
            'NOT_FOUND', 'Receipt was not found.', 404)
    return receipt, None


class OrderReceiptView(APIView):
    """Metadata for the receipt of one order (customer-facing)."""

    def get(self, request, order_number):
        order = Order.objects.select_related('cart').filter(
            order_number=order_number).first()
        if order is None:
            return _error('NOT_FOUND', 'Order was not found.', 404)
        if not _can_access_order(request, order):
            return _error(
                'FORBIDDEN', 'You cannot access this order.', 403)
        if not _order_receipt_visible(order):
            return _not_ready_error()
        receipt = Receipt.objects.filter(order=order).first()
        if receipt is None:
            return _error(
                'RECEIPT_NOT_FOUND',
                'No receipt has been issued for this order yet.', 404)
        return Response(ReceiptSerializer(receipt).data)


class ReceiptDownloadView(APIView):
    """Stream the receipt PDF to the owning customer."""

    def get(self, request, receipt_number):
        receipt, err = _receipt_or_404(receipt_number)
        if err is not None:
            return err
        if not _can_access_order(request, receipt.order):
            return _error(
                'FORBIDDEN', 'You cannot access this receipt.', 403)
        if not _order_receipt_visible(receipt.order):
            return _not_ready_error()
        try:
            pdf_bytes = read_pdf_bytes(receipt)
        except Exception:
            logger.exception(
                'Receipt PDF read failed for %s.', receipt.receipt_number)
            AuditLogService.log(
                'receipt_downloaded',
                object_type='receipt',
                object_id=receipt.pk,
                object_repr=receipt.receipt_number,
                category='payments',
                result='failure',
                metadata={'reason': 'storage_read_failed'},
                description=f'Receipt {receipt.receipt_number} download failed.',
            )
            return _error(
                'DOCUMENT_UNAVAILABLE',
                'The receipt document is temporarily unavailable.', 500)

        AuditLogService.log(
            'receipt_downloaded',
            object_type='receipt',
            object_id=receipt.pk,
            object_repr=receipt.receipt_number,
            category='payments',
            metadata={'order_number': receipt.order.order_number},
            description=f'Receipt {receipt.receipt_number} downloaded.',
        )
        from io import BytesIO
        return FileResponse(
            BytesIO(pdf_bytes),
            content_type='application/pdf',
            as_attachment=True,
            filename=f'{receipt.receipt_number}.pdf',
        )


class AdminReceiptRegenerateView(APIView):
    """Repair path for a failed or stale receipt (staff/admin only)."""

    permission_classes = [IsStaffOrAdmin]

    def post(self, request, receipt_number):
        receipt, err = _receipt_or_404(receipt_number)
        if err is not None:
            return err
        try:
            receipt = regenerate_receipt(receipt)
        except Exception:
            logger.exception(
                'Receipt regeneration failed for %s.', receipt_number)
            return _error(
                'RECEIPT_REGENERATION_FAILED',
                'The receipt could not be regenerated.', 500)
        return Response(ReceiptSerializer(receipt).data)
