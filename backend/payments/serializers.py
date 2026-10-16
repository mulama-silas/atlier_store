from rest_framework import serializers

from catalog.serializers import major_units

from .models import PaymentIntent


class PaymentIntentSerializer(serializers.ModelSerializer):
    orderNumber = serializers.CharField(source='order.order_number')
    amount = serializers.SerializerMethodField()
    gatewayReference = serializers.CharField(
        source='gateway_reference', allow_blank=True)

    class Meta:
        model = PaymentIntent
        fields = ('id', 'orderNumber', 'amount', 'currency', 'method',
                  'status', 'gatewayReference')

    def get_amount(self, obj):
        return major_units(obj.amount_minor)
