import secrets
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import AuditLogService
from orders.serializers import OrderSerializer

from .serializers import PaymentIntentSerializer
from .daraja import query_stk_status
from .models import PaymentIntent
from .services import (
    _mark_intent_succeeded,
    confirm_payment,
    create_intent,
    get_order_for_cart,
    process_webhook,
)


class CreatePaymentIntentView(APIView):
    throttle_scope = 'payments'

    def post(self, request):
        intent = create_intent(
            request.data.get('orderNumber', ''),
            request.data.get('method', 'mpesa'),
            request.data.get('phoneNumber'),
            request.headers.get('x-cart-id'),
            request.user,
        )
        return Response(PaymentIntentSerializer(intent).data, status=201)


class ConfirmPaymentView(APIView):
    throttle_scope = 'payments'

    def post(self, request):
        order = confirm_payment(
            request.data.get('orderNumber', ''),
            request.data.get('paymentIntentId', ''),
            request.data.get('gatewayReference'),
            request.headers.get('x-cart-id'),
            request.user,
        )
        return Response(OrderSerializer(order).data)


class PaymentStatusView(APIView):
    throttle_scope = 'payments'

    def get(self, request):
        order = get_order_for_cart(
            request.query_params.get('orderNumber', ''),
            request.headers.get('x-cart-id'), request.user,
        )
        intent = PaymentIntent.objects.filter(
            id=request.query_params.get('paymentIntentId', ''), order=order,
        ).first()
        if not intent:
            return Response({'detail': 'Payment attempt was not found.'}, status=404)
        return Response({
            'status': intent.status,
            'orderNumber': order.order_number,
            'failureMessage': intent.failure_message if intent.status == PaymentIntent.Status.FAILED else '',
        })


class PaymentWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = 'payments'

    def post(self, request):
        signature = request.headers.get('x-webhook-signature')
        event_id = request.headers.get(
            'x-event-id') or request.data.get('eventId')
        if not signature or not secrets.compare_digest(
                signature, settings.PAYMENT_WEBHOOK_SECRET):
            AuditLogService.log(
                'security_event',
                category='security',
                result='failure',
                severity='critical',
                metadata={'event_type': (request.data or {}).get('event', ''),
                          'has_signature': bool(signature)},
                path=request.path,
                description='Payment webhook rejected with an invalid signature.',
            )
        result = process_webhook(request.data, signature, event_id)
        return Response(result)


class MpesaCallbackView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = 'payments'

    def post(self, request):
        payload = request.data
        if not isinstance(payload, dict) or not isinstance(payload.get('Body'), dict):
            return Response({'ResponseCode': '1', 'ResponseDescription': 'Malformed callback.'}, status=400)
        callback = payload['Body'].get('stkCallback')
        if not isinstance(callback, dict):
            return Response({'ResponseCode': '1', 'ResponseDescription': 'Malformed callback.'}, status=400)
        checkout_id = callback.get('CheckoutRequestID')
        merchant_id = callback.get('MerchantRequestID')
        if not isinstance(checkout_id, str) or not checkout_id or not isinstance(merchant_id, str):
            return Response({'ResponseCode': '1', 'ResponseDescription': 'Malformed callback.'}, status=400)
        intent = PaymentIntent.objects.filter(checkout_request_id=checkout_id,
                                              merchant_request_id=merchant_id).select_related('order').first()
        if not intent:
            # Acknowledge unknown/replayed events without revealing order data.
            return Response({'ResponseCode': '0', 'ResponseDescription': 'Accepted'})
        if intent.status != PaymentIntent.Status.PENDING:
            return Response({'ResponseCode': '0', 'ResponseDescription': 'Accepted'})
        try:
            verified = query_stk_status(checkout_id)
        except Exception as exc:
            logger = __import__('logging').getLogger('payments')
            logger.warning('Daraja callback verification deferred (%s).', type(exc).__name__)
            return Response({'ResponseCode': '0', 'ResponseDescription': 'Received; verification pending'})
        if verified.get('CheckoutRequestID') != checkout_id or verified.get('ResponseCode') != '0':
            return Response({'ResponseCode': '0', 'ResponseDescription': 'Received; verification pending'})
        try:
            result_code = int(verified.get('ResultCode'))
        except (TypeError, ValueError):
            return Response({'ResponseCode': '0', 'ResponseDescription': 'Received; verification pending'})
        if result_code == 0:
            callback_metadata = callback.get('CallbackMetadata') or {}
            if not isinstance(callback_metadata, dict) or not isinstance(callback_metadata.get('Item'), list):
                return Response({'ResponseCode': '0', 'ResponseDescription': 'Received; verification pending'})
            items = callback_metadata['Item']
            values = {item.get('Name'): item.get('Value') for item in items if isinstance(item, dict)}
            receipt = values.get('MpesaReceiptNumber')
            try:
                amount_decimal = Decimal(str(values.get('Amount')))
                callback_amount = amount_decimal * 100
            except (TypeError, ValueError, InvalidOperation):
                callback_amount = -1
            if (not isinstance(receipt, str) or not receipt or
                    callback_amount != Decimal(intent.amount_minor) or
                    str(callback.get('ResultCode', '')) != '0'):
                return Response({'ResponseCode': '0', 'ResponseDescription': 'Received; verification pending'})
            with transaction.atomic():
                locked = PaymentIntent.objects.select_for_update().select_related('order').get(pk=intent.pk)
                if locked.status == PaymentIntent.Status.PENDING:
                    locked.gateway_reference = receipt[:160]
                    locked.save(update_fields=['gateway_reference', 'updated_at'])
                    _mark_intent_succeeded(locked, receipt)
        else:
            # Callback failure is finalized only after authenticated Daraja query.
            with transaction.atomic():
                locked = PaymentIntent.objects.select_for_update().get(pk=intent.pk)
                if locked.status == PaymentIntent.Status.PENDING:
                    locked.status = PaymentIntent.Status.FAILED
                    locked.failure_code = str(result_code)[:80]
                    locked.failure_message = 'M-Pesa payment was not completed.'
                    locked.save(update_fields=['status', 'failure_code', 'failure_message', 'updated_at'])
        return Response({'ResponseCode': '0', 'ResponseDescription': 'Accepted'})
