from rest_framework import serializers

from catalog.models import Category, Product


class ProductWriteSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=200)
    slug = serializers.SlugField(max_length=100)
    description = serializers.CharField(min_length=10)
    tagline = serializers.CharField(
        max_length=255, required=False, allow_blank=True)
    details = serializers.ListField(
        child=serializers.CharField(), required=False)
    material = serializers.CharField(max_length=160, required=False, allow_blank=True)
    careInstructions = serializers.CharField(required=False, allow_blank=True)
    fitNotes = serializers.CharField(required=False, allow_blank=True)
    modelSize = serializers.CharField(max_length=40, required=False, allow_blank=True)
    garmentMeasurements = serializers.JSONField(required=False)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0)
    compareAtPrice = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True)
    categoryId = serializers.UUIDField()
    images = serializers.ListField(
        child=serializers.CharField(), required=False)
    status = serializers.ChoiceField(
        choices=Product.Status.choices, required=False)
    isFeatured = serializers.BooleanField(required=False)
    isNewArrival = serializers.BooleanField(required=False)
    isBestSeller = serializers.BooleanField(required=False)

    def validate(self, attrs):
        compare_at = attrs.get('compareAtPrice')
        if compare_at is not None and compare_at <= attrs['price']:
            raise serializers.ValidationError(
                {'compareAtPrice': 'Must be greater than price.'})
        return attrs


class CategoryWriteSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=120)
    slug = serializers.SlugField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)
    imageUrl = serializers.URLField(required=False, allow_blank=True)
    isActive = serializers.BooleanField(required=False)


class StockAdjustmentSerializer(serializers.Serializer):
    delta = serializers.IntegerField(min_value=-100000, max_value=100000)
    reason = serializers.CharField(min_length=2, max_length=40)
