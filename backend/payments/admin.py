from django.contrib import admin

from .models import PaymentEvent, PaymentIntent


@admin.register(PaymentIntent)
class PaymentIntentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'amount_minor', 'method',
                    'status', 'gateway_reference', 'created_at')
    list_filter = ('method', 'status', 'currency')
    search_fields = ('id', 'order__order_number', 'gateway_reference')
    readonly_fields = ('id', 'order', 'amount_minor', 'currency', 'method', 'status',
                       'checkout_request_id', 'gateway_reference', 'metadata', 'created_at', 'updated_at')


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'payment_intent', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('event_id', 'event_type', 'payment_intent__id')
    readonly_fields = ('event_id', 'payment_intent',
                       'event_type', 'payload', 'created_at')
