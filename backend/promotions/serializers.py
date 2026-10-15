from rest_framework import serializers

from catalog.models import Category, Product, ProductVariant

from .models import Promotion, normalize_coupon_code


class PromotionWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    promotion_type = serializers.ChoiceField(choices=[c for c, _ in Promotion.Type.choices])
    status = serializers.ChoiceField(
        choices=[c for c, _ in Promotion.Status.choices], default='draft')
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = serializers.FloatField(default=0)  # major units in API
    maximum_discount = serializers.FloatField(required=False, allow_null=True, default=None)
    minimum_order_value = serializers.FloatField(default=0)
    minimum_quantity = serializers.IntegerField(default=0, min_value=0)
    qualifying_quantity = serializers.IntegerField(default=0, min_value=0)
    reward_quantity = serializers.IntegerField(default=0, min_value=0)
    reward_discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, default=100)
    max_redemptions_per_order = serializers.IntegerField(required=False, allow_null=True, default=None)
    coupon_code = serializers.CharField(required=False, allow_blank=True, default='')
    is_automatic = serializers.BooleanField(default=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    ends_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    usage_limit = serializers.IntegerField(required=False, allow_null=True, default=None)
    usage_limit_per_customer = serializers.IntegerField(required=False, allow_null=True, default=None)
    priority = serializers.IntegerField(default=10)
    stackable = serializers.BooleanField(default=False)
    eligible_all = serializers.BooleanField(default=True)
    sale_only = serializers.BooleanField(default=False)
    new_only = serializers.BooleanField(default=False)
    customer_scope = serializers.ChoiceField(
        choices=[c for c, _ in Promotion.CustomerScope.choices], default='all')
    product_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    category_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    variant_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    customer_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)

    def validate(self, data):
        if float(data.get('discount_percent') or 0) < 0 or float(data.get('discount_percent') or 0) > 100:
            raise serializers.ValidationError({'discount_percent': 'Must be between 0 and 100.'})
        if float(data.get('discount_amount') or 0) < 0:
            raise serializers.ValidationError({'discount_amount': 'Must be >= 0.'})
        starts, ends = data.get('starts_at'), data.get('ends_at')
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({'ends_at': 'End must be after start.'})
        if data.get('status') == Promotion.Status.ACTIVE and not ends:
            raise serializers.ValidationError(
                {'ends_at': 'Set an end date before publishing this promotion.'})
        ptype = data.get('promotion_type')
        if ptype in ('buy_x_get_y', 'buy_x_get_pct') and (
                (data.get('qualifying_quantity') or 0) <= 0 or (data.get('reward_quantity') or 0) <= 0):
            raise serializers.ValidationError(
                {'qualifying_quantity': 'Buy X Get Y requires qualifying and reward quantities.'})
        if not data.get('is_automatic') and not normalize_coupon_code(data.get('coupon_code') or ''):
            raise serializers.ValidationError({'coupon_code': 'Non-automatic promotions require a coupon code.'})
        return data


def promotion_to_dict(promo, redemptions=None):
    return {
        'id': str(promo.pk),
        'name': promo.name,
        'description': promo.description,
        'type': promo.promotion_type,
        'code': promo.coupon_code or '',
        'status': promo.status,
        'isAutomatic': promo.is_automatic,
        'discountPercent': float(promo.discount_percent or 0),
        'discountAmount': (promo.discount_amount_minor or 0) / 100,
        'maximumDiscount': (promo.maximum_discount_minor / 100) if promo.maximum_discount_minor is not None else None,
        'minimumOrderValue': (promo.minimum_order_value_minor or 0) / 100,
        'minimumQuantity': promo.minimum_quantity,
        'qualifyingQuantity': promo.qualifying_quantity,
        'rewardQuantity': promo.reward_quantity,
        'rewardDiscountPercent': float(promo.reward_discount_percent or 0),
        'startsAt': promo.starts_at.isoformat() if promo.starts_at else None,
        'endsAt': promo.ends_at.isoformat() if promo.ends_at else None,
        'usageLimit': promo.usage_limit,
        'usageLimitPerCustomer': promo.usage_limit_per_customer,
        'usageCount': redemptions if redemptions is not None else promo.redemptions.filter(voided=False).count(),
        'priority': promo.priority,
        'stackable': promo.stackable,
        'customerScope': promo.customer_scope,
    }


def apply_write_data(promo, data, user=None):
    promo.name = data['name']
    promo.description = data.get('description', '')
    promo.promotion_type = data['promotion_type']
    promo.status = data.get('status', 'draft')
    promo.discount_percent = data.get('discount_percent') or 0
    promo.discount_amount_minor = int(round(float(data.get('discount_amount') or 0) * 100))
    maxd = data.get('maximum_discount')
    promo.maximum_discount_minor = None if maxd is None else int(round(float(maxd) * 100))
    promo.minimum_order_value_minor = int(round(float(data.get('minimum_order_value') or 0) * 100))
    promo.minimum_quantity = data.get('minimum_quantity') or 0
    promo.qualifying_quantity = data.get('qualifying_quantity') or 0
    promo.reward_quantity = data.get('reward_quantity') or 0
    promo.reward_discount_percent = data.get('reward_discount_percent') or 100
    promo.max_redemptions_per_order = data.get('max_redemptions_per_order')
    promo.coupon_code = (data.get('coupon_code') or '').strip()
    promo.is_automatic = bool(data.get('is_automatic'))
    promo.starts_at = data.get('starts_at')
    promo.ends_at = data.get('ends_at')
    promo.usage_limit = data.get('usage_limit')
    promo.usage_limit_per_customer = data.get('usage_limit_per_customer')
    promo.priority = data.get('priority', 10)
    promo.stackable = bool(data.get('stackable'))
    promo.eligible_all = bool(data.get('eligible_all', True))
    promo.sale_only = bool(data.get('sale_only'))
    promo.new_only = bool(data.get('new_only'))
    promo.customer_scope = data.get('customer_scope', 'all')
    if user is not None and getattr(user, 'is_authenticated', False):
        if promo.pk is None:
            promo.created_by = user
        promo.updated_by = user
    promo.save()
    # Replace targeting sets.
    from .models import PromotionCategory, PromotionCustomer, PromotionProduct, PromotionVariant
    PromotionProduct.objects.filter(promotion=promo).delete()
    PromotionCategory.objects.filter(promotion=promo).delete()
    PromotionVariant.objects.filter(promotion=promo).delete()
    PromotionCustomer.objects.filter(promotion=promo).delete()
    for pid in data.get('product_ids') or []:
        product = Product.objects.filter(pk=pid).first()
        if product is not None:
            PromotionProduct.objects.get_or_create(promotion=promo, product=product)
    for cid in data.get('category_ids') or []:
        category = Category.objects.filter(pk=cid).first()
        if category is not None:
            PromotionCategory.objects.get_or_create(promotion=promo, category=category)
    for vid in data.get('variant_ids') or []:
        variant = ProductVariant.objects.filter(pk=vid).select_related('product').first()
        if variant is not None:
            PromotionVariant.objects.get_or_create(promotion=promo, variant=variant)
    if promo.customer_scope == 'specific':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        for uid in data.get('customer_ids') or []:
            target = User.objects.filter(pk=uid).first()
            if target is not None:
                PromotionCustomer.objects.get_or_create(promotion=promo, user=target)
    if not data.get('eligible_all', True) and not (
            (data.get('product_ids') or []) or (data.get('category_ids') or []) or (data.get('variant_ids') or [])):
        pass
    return promo
