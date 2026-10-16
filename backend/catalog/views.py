from uuid import UUID
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Min, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.services import subscribe_to_stock_alert
from accounts.permissions import IsAuthenticatedSupabaseUser
from orders.models import Order

from .models import Category, Product, ProductReview, ProductVariant
from .serializers import CategorySerializer, ProductReviewSerializer, ProductSerializer


OCCASION_CATEGORY_SLUGS = {
    'everyday': ('women', 'men', 'tops', 'bottoms', 'shoes'),
    'evening': ('dresses', 'outerwear'),
    'special-occasions': ('dresses', 'accessories', 'outerwear'),
}


def with_review_summary(queryset):
    return queryset.annotate(
        approved_review_count=Count('reviews', filter=Q(reviews__is_approved=True), distinct=True),
        approved_average_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
    )


def product_identifier_query(identifier):
    query = Q(slug=identifier)
    try:
        product_id = UUID(identifier)
    except (ValueError, TypeError):
        return query
    return query | Q(pk=product_id)


class BackInStockView(APIView):
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        variant_id = data.get('variantId', '')
        email = data.get('email', '')
        try:
            _, created = subscribe_to_stock_alert(variant_id, email)
        except Exception as exc:  # noqa: BLE001 - normalise to API contract
            error = getattr(exc, 'detail', None)
            if isinstance(error, dict):
                return Response(
                    {'error': {'code': 'VALIDATION_ERROR',
                               'message': 'Subscription could not be saved.',
                               'details': error}},
                    status=400)
            raise
        return Response({
            'ok': True,
            'alreadySubscribed': not created,
            'message': 'We will notify you when this item is back in stock.',
        }, status=201 if created else 200)


class ProductListView(APIView):
    def get(self, request):
        products = Product.objects.filter(
            status=Product.Status.ACTIVE,
            category__is_active=True,
        ).select_related('category').prefetch_related(
            'product_images', 'variants__variant_images')
        category = request.query_params.get('category')
        search = request.query_params.get('search', '').strip()
        sort = request.query_params.get('sort', 'newest')
        try:
            page = max(int(request.query_params.get('page', 1)), 1)
            limit = min(max(int(request.query_params.get('limit', 20)), 1), 100)
        except (TypeError, ValueError):
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'Page and limit must be whole numbers.', 'details': {}}}, status=400)

        if category and category != 'all':
            category_filter = Q(category__slug=category)
            try:
                UUID(category)
            except ValueError:
                pass
            else:
                category_filter |= Q(category_id=category)
            products = products.filter(category_filter)
        if search:
            products = products.filter(Q(name__icontains=search) | Q(
                description__icontains=search) | Q(tagline__icontains=search))
        collection = request.query_params.get('collection', '')
        if collection == 'best-sellers':
            products = products.filter(is_best_seller=True)
        elif collection == 'new-arrivals':
            products = products.filter(is_new_arrival=True)
        occasion = request.query_params.get('occasion', '')
        if occasion in OCCASION_CATEGORY_SLUGS:
            products = products.filter(category__slug__in=OCCASION_CATEGORY_SLUGS[occasion])
        if request.query_params.get('sale', '').lower() == 'true':
            products = products.filter(compare_at_price_minor__gt=F('price_minor'))
        products = products.annotate(
            filter_price_minor=Min(Coalesce('variants__price_minor', F('price_minor'))))
        for param, lookup in (('minPrice', 'gte'), ('maxPrice', 'lte')):
            raw = request.query_params.get(param)
            if raw:
                try:
                    amount = Decimal(raw)
                    if not amount.is_finite() or amount < 0:
                        raise InvalidOperation
                    amount_minor = int(amount * 100)
                except (InvalidOperation, ValueError, OverflowError):
                    return Response({'error': {'code': 'VALIDATION_ERROR', 'message': f'{param} must be a non-negative price.', 'details': {}}}, status=400)
                products = products.filter(**{f'filter_price_minor__{lookup}': amount_minor})
        size = request.query_params.get('size', '').strip()
        color = request.query_params.get('color', '').strip()
        variant_filters = {}
        if size:
            variant_filters['variants__size__iexact'] = size
        if color:
            variant_filters['variants__color__iexact'] = color
        if request.query_params.get('inStock', '').lower() == 'true':
            variant_filters['variants__stock_quantity__gt'] = 0
        if variant_filters:
            variant_filters['variants__is_active'] = True
            products = products.filter(**variant_filters)
        products = products.distinct()
        if sort in ('price_asc', 'price:asc', 'price-asc'):
            products = products.order_by('filter_price_minor')
        elif sort in ('price_desc', 'price:desc', 'price-desc'):
            products = products.order_by('-filter_price_minor')
        elif sort == 'name':
            products = products.order_by('name')
        elif sort == 'featured':
            products = products.order_by('-is_featured', '-created_at')
        else:
            products = products.order_by('-created_at')

        total = products.count()
        total_pages = max((total + limit - 1) // limit, 1)
        products = products[(page - 1) * limit:page * limit]
        return Response({
            'data': ProductSerializer(with_review_summary(products), many=True,
                                      context={'request': request}).data,
            'pagination': {'page': page, 'limit': limit, 'total': total, 'totalPages': total_pages},
            'facets': {
                'sizes': list(ProductVariant.objects.filter(product__status=Product.Status.ACTIVE, is_active=True).exclude(size='').order_by('size').values_list('size', flat=True).distinct()),
                'colors': list(ProductVariant.objects.filter(product__status=Product.Status.ACTIVE, is_active=True).exclude(color='').order_by('color').values_list('color', flat=True).distinct()),
            },
        })


class ProductDetailView(APIView):
    def get(self, request, identifier):
        product_lookup = Q(slug=identifier)
        try:
            UUID(identifier)
        except ValueError:
            pass
        else:
            product_lookup |= Q(id=identifier)
        product = get_object_or_404(
            with_review_summary(Product.objects.select_related(
                'category').prefetch_related('product_images', 'variants__variant_images')),
            product_lookup,
            status=Product.Status.ACTIVE,
            category__is_active=True,
        )
        return Response(ProductSerializer(
            product, context={'request': request}).data)


class CategoryListView(APIView):
    def get(self, request):
        categories = Category.objects.filter(is_active=True)
        return Response(CategorySerializer(categories, many=True).data)


class CategoryDetailView(APIView):
    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug, is_active=True)
        products = category.products.filter(
            status=Product.Status.ACTIVE).prefetch_related(
                'product_images', 'variants__variant_images')
        return Response({
            'category': CategorySerializer(category).data,
            'products': ProductSerializer(
                with_review_summary(products), many=True, context={'request': request}).data,
        })


class ProductReviewsView(APIView):
    def get_permissions(self):
        return [IsAuthenticatedSupabaseUser()] if self.request.method == 'POST' else [AllowAny()]

    def get(self, request, identifier):
        product = get_object_or_404(Product, product_identifier_query(identifier),
                                    status=Product.Status.ACTIVE,
                                    category__is_active=True)
        reviews = ProductReview.objects.filter(
            product=product, is_approved=True).select_related('user')
        return Response({'results': ProductReviewSerializer(reviews, many=True).data})

    def post(self, request, identifier):
        product = get_object_or_404(Product, product_identifier_query(identifier),
                                    status=Product.Status.ACTIVE,
                                    category__is_active=True)
        purchased = Order.objects.filter(
            user=request.user,
            status__in=(Order.Status.DELIVERED, Order.Status.RECEIVED),
            items__product=product,
        ).exists()
        if not purchased:
            return Response({'error': {'code': 'PURCHASE_REQUIRED',
                                       'message': 'Reviews are available to customers with a delivered order for this item.',
                                       'details': {}}}, status=status.HTTP_403_FORBIDDEN)
        serializer = ProductReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': {'code': 'VALIDATION_ERROR',
                                       'message': 'Review details are invalid.',
                                       'details': serializer.errors}}, status=400)
        try:
            with transaction.atomic():
                review = serializer.save(product=product, user=request.user)
        except IntegrityError:
            return Response({'error': {'code': 'REVIEW_EXISTS',
                                       'message': 'You have already reviewed this item.',
                                       'details': {}}}, status=409)
        return Response({'id': str(review.pk),
                         'message': 'Thank you. Your verified review is awaiting moderation.'},
                        status=status.HTTP_201_CREATED)
