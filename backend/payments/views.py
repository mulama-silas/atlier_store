import secrets

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import AuditLogService
from orders.serializers import OrderSerializer

from .serializers import PaymentIntentSerializer
from .models import PaymentIntent
from .services import confirm_payment, create_intent, process_webhook


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
        if request.query_params.get('token') != settings.MPESA_CALLBACK_SECRET:
            AuditLogService.log(
                'security_event',
                category='security',
                result='failure',
                severity='critical',
                metadata={'ip_address': request.META.get('REMOTE_ADDR', ''),
                          'has_token': bool(request.query_params.get('token'))},
                path=request.path,
                description='Unauthorized M-Pesa callback attempt.',
            )
            return Response({'ResponseCode': '1', 'ResponseDescription': 'Unauthorized callback.'}, status=401)
        callback = request.data.get('Body', {}).get('stkCallback', {})
        checkout_id = callback.get('CheckoutRequestID')
        intent = PaymentIntent.objects.filter(
            client_secret=checkout_id).first()
        if not intent:
            return Response({'ResponseCode': '1', 'ResponseDescription': 'Payment intent was not found.'}, status=404)
        metadata = callback.get('CallbackMetadata', {}).get('Item', [])
        transaction_id = next((item.get('Value') for item in metadata if item.get(
            'Name') == 'MpesaReceiptNumber'), '')
        successful = callback.get('ResultCode') == 0
        result = process_webhook(
            {
                'event': 'mpesa.stk_callback.success' if successful else 'mpesa.stk_callback.failed',
                'data': {
                    'paymentIntentId': intent.id,
                    'transactionId': transaction_id,
                },
            },
            settings.PAYMENT_WEBHOOK_SECRET,
            checkout_id,
        )
        return Response({'ResponseCode': '0', 'ResponseDescription': 'Accepted', **result})
