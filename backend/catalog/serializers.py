from rest_framework import serializers
from django.db.models import Avg

from .models import Category, Product, ProductReview, ProductVariant


def major_units(minor_units):
    return minor_units / 100


class CategorySerializer(serializers.ModelSerializer):
    imageUrl = serializers.CharField(source='image_url', allow_blank=True)
    isActive = serializers.BooleanField(source='is_active')

    class Meta:
        model = Category
        fields = ('id', 'name', 'slug', 'description', 'imageUrl', 'isActive')


class ProductVariantSerializer(serializers.ModelSerializer):
    colorHex = serializers.CharField(source='color_hex', allow_blank=True)
    stockQuantity = serializers.IntegerField(source='stock_quantity')
    isAvailable = serializers.SerializerMethodField()
    isActive = serializers.BooleanField(source='is_active')
    price = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ('id', 'sku', 'size', 'color', 'colorHex', 'price',
                  'stockQuantity', 'isAvailable', 'isActive', 'images')

    def get_price(self, obj):
        return major_units(obj.price_minor if obj.price_minor is not None else obj.product.price_minor)

    def get_images(self, obj):
        request = self.context.get('request')
        urls = [image.image_url for image in obj.variant_images.all() if image.image_url]
        if request:
            return [request.build_absolute_uri(url) if url.startswith('/') else url for url in urls]
        return urls

    def get_isAvailable(self, obj):
        return obj.is_active and obj.stock_quantity > 0


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    compareAtPrice = serializers.SerializerMethodField()
    isFeatured = serializers.BooleanField(source='is_featured')
    isNewArrival = serializers.BooleanField(source='is_new_arrival')
    isBestSeller = serializers.BooleanField(source='is_best_seller')
    createdAt = serializers.DateTimeField(source='created_at')
    updatedAt = serializers.DateTimeField(source='updated_at')
    price = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, read_only=True)
    averageRating = serializers.SerializerMethodField()
    reviewCount = serializers.SerializerMethodField()
    careInstructions = serializers.CharField(source='care_instructions', read_only=True)
    fitNotes = serializers.CharField(source='fit_notes', read_only=True)
    modelSize = serializers.CharField(source='model_size', read_only=True)
    garmentMeasurements = serializers.JSONField(source='garment_measurements', read_only=True)

    class Meta:
        model = Product
        fields = (
            'id', 'name', 'slug', 'tagline', 'description', 'details', 'price', 'compareAtPrice',
            'category', 'images', 'status', 'isFeatured', 'isNewArrival', 'isBestSeller',
            'variants', 'createdAt', 'updatedAt', 'material', 'careInstructions',
            'fitNotes', 'modelSize', 'garmentMeasurements', 'averageRating', 'reviewCount',
        )

    def get_category(self, obj):
        return {'id': str(obj.category_id), 'name': obj.category.name, 'slug': obj.category.slug}

    def get_images(self, obj):
        request = self.context.get('request')
        images = Product.normalize_images(obj.images)
        if request:
            return [request.build_absolute_uri(image) if image.startswith('/') else image for image in images]
        return images

    def get_price(self, obj):
        return major_units(obj.price_minor)

    def get_compareAtPrice(self, obj):
        return major_units(obj.compare_at_price_minor) if obj.compare_at_price_minor is not None else None

    def get_averageRating(self, obj):
        if hasattr(obj, 'approved_average_rating'):
            value = obj.approved_average_rating
        else:
            value = obj.reviews.filter(is_approved=True).aggregate(value=Avg('rating'))['value']
        return round(float(value), 1) if value is not None else None

    def get_reviewCount(self, obj):
        if hasattr(obj, 'approved_review_count'):
            return obj.approved_review_count
        return obj.reviews.filter(is_approved=True).count()


class ProductReviewSerializer(serializers.ModelSerializer):
    displayName = serializers.SerializerMethodField()
    isVerified = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = ProductReview
        fields = ('id', 'rating', 'title', 'body', 'displayName', 'isVerified', 'createdAt')
        read_only_fields = ('id', 'displayName', 'isVerified', 'createdAt')

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError('Choose a rating from 1 to 5 stars.')
        return value

    def get_displayName(self, obj):
        first = (obj.user.first_name or '').strip()
        last = (obj.user.last_name or '').strip()
        if first and last:
            return f'{first} {last[0]}.'
        return first or 'Verified customer'

    def get_isVerified(self, obj):
        return True
