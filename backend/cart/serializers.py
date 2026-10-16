from rest_framework import serializers

from catalog.serializers import major_units

from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    productId = serializers.UUIDField(source='variant.product_id')
    variantId = serializers.UUIDField(source='variant_id')
    product = serializers.SerializerMethodField()
    variant = serializers.SerializerMethodField()
    unitPrice = serializers.SerializerMethodField()
    lineTotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ('id', 'productId', 'variantId', 'product',
                  'variant', 'quantity', 'unitPrice', 'lineTotal')

    def _image_url(self, image, request):
        if not image:
            return ''
        if image.startswith('http://') or image.startswith('https://'):
            return image
        if image.startswith('/') and request:
            return request.build_absolute_uri(image)
        if image.startswith('/'):
            return image
        return image

    def get_product(self, obj):
        product = obj.variant.product
        request = self.context.get('request')
        image = (product.images or [''])[0]
        return {
            'id': str(product.id),
            'name': product.name,
            'slug': product.slug,
            'image': self._image_url(image, request),
        }

    def get_variant(self, obj):
        variant = obj.variant
        return {
            'id': str(variant.id),
            'sku': variant.sku,
            'size': variant.size,
            'color': variant.color,
            'stockQuantity': variant.stock_quantity,
        }

    def get_unitPrice(self, obj):
        price_minor = obj.variant.price_minor
        if price_minor is None:
            price_minor = obj.variant.product.price_minor
        return major_units(price_minor)

    def get_lineTotal(self, obj):
        return self.get_unitPrice(obj) * obj.quantity


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    itemCount = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    shippingDiscount = serializers.SerializerMethodField()
    tax = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    promotion = serializers.SerializerMethodField()
    appliedPromotions = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ('id', 'items', 'subtotal', 'itemCount', 'currency',
                  'discount', 'shippingDiscount', 'tax', 'total',
                  'promotion', 'appliedPromotions')

    def _pricing(self, obj):
        if '_promo_pricing' not in self.context:
            try:
                from promotions.services import price_cart
                request = self.context.get('request')
                user = getattr(request, 'user', None)
                if user is not None and getattr(user, 'is_anonymous', False):
                    user = None
                self.context['_promo_pricing'] = price_cart(
                    obj, user=user, shipping_method='standard',
                    coupon_code=getattr(obj, 'coupon_code', '') or '')
            except Exception:
                self.context['_promo_pricing'] = None
        return self.context.get('_promo_pricing')

    def get_discount(self, obj):
        pricing = self._pricing(obj)
        return (pricing['discount'] / 100) if pricing else 0

    def get_shippingDiscount(self, obj):
        pricing = self._pricing(obj)
        return (pricing['shipping_discount'] / 100) if pricing else 0

    def get_tax(self, obj):
        pricing = self._pricing(obj)
        return (pricing['tax'] / 100) if pricing else 0

    def get_total(self, obj):
        pricing = self._pricing(obj)
        if pricing:
            return pricing['total'] / 100
        return self.get_subtotal(obj)

    def get_promotion(self, obj):
        pricing = self._pricing(obj)
        if not pricing or not pricing.get('applied'):
            return None
        from promotions.models import normalize_coupon_code
        cart_code = normalize_coupon_code(getattr(obj, 'coupon_code', '') or '')
        primary = next(
            (entry for entry in pricing['applied']
             if cart_code and normalize_coupon_code(entry.get('code')) == cart_code),
            pricing['applied'][0],
        )
        return {'code': primary['code'], 'name': primary['name'],
                'discount': primary['discount'] / 100, 'type': primary['type']}

    def get_appliedPromotions(self, obj):
        pricing = self._pricing(obj)
        if not pricing:
            return []
        return [{'code': a['code'], 'name': a['name'], 'type': a['type'],
                 'discount': a['discount'] / 100,
                 'shippingDiscount': a.get('shipping_discount', 0) / 100}
                for a in pricing.get('applied', [])]

    def get_subtotal(self, obj):
        return sum(item.line_total_minor for item in self._priced_items(obj)) / 100

    def get_itemCount(self, obj):
        return sum(item.quantity for item in obj.items.all())

    def get_currency(self, obj):
        return 'KES'

    def _priced_items(self, obj):
        items = list(obj.items.select_related('variant__product').all())
        for item in items:
            price_minor = item.variant.price_minor
            if price_minor is None:
                price_minor = item.variant.product.price_minor
            item.line_total_minor = price_minor * item.quantity
        return items
