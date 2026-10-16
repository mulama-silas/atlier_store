from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from rest_framework.exceptions import NotFound

from catalog.models import Category, Product


def to_minor(amount):
    return int((amount * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def product_values(data):
    images = data.get('images') or []
    values = {
        'name': data['name'],
        'slug': data['slug'],
        'description': data['description'],
        'tagline': data.get('tagline', ''),
        'details': data.get('details', []),
        'material': data.get('material', ''),
        'care_instructions': data.get('careInstructions', ''),
        'fit_notes': data.get('fitNotes', ''),
        'model_size': data.get('modelSize', ''),
        'garment_measurements': data.get('garmentMeasurements', {}),
        'price_minor': to_minor(data['price']),
        'compare_at_price_minor': to_minor(data['compareAtPrice']) if data.get('compareAtPrice') is not None else None,
        'images': images,
        'status': data.get('status', Product.Status.ACTIVE),
        'is_featured': data.get('isFeatured', False),
        'is_new_arrival': data.get('isNewArrival', False),
        'is_best_seller': data.get('isBestSeller', False),
    }
    return values


@transaction.atomic
def create_product(data):
    category = Category.objects.filter(pk=data['categoryId']).first()
    if not category:
        raise NotFound('Category was not found.')
    return Product.objects.create(category=category, **product_values(data))


@transaction.atomic
def update_product(product, data):
    values = product_values({**{
        'name': product.name,
        'slug': product.slug,
        'description': product.description,
        'tagline': product.tagline,
        'details': product.details,
        'material': product.material,
        'careInstructions': product.care_instructions,
        'fitNotes': product.fit_notes,
        'modelSize': product.model_size,
        'garmentMeasurements': product.garment_measurements,
        'price': Decimal(product.price_minor) / 100,
        'compareAtPrice': Decimal(product.compare_at_price_minor) / 100 if product.compare_at_price_minor is not None else None,
        'categoryId': product.category_id,
        'images': product.images,
        'status': product.status,
        'isFeatured': product.is_featured,
        'isNewArrival': product.is_new_arrival,
        'isBestSeller': product.is_best_seller,
    }, **data})
    if 'categoryId' in data:
        product.category = Category.objects.get(pk=data['categoryId'])
    for field, value in values.items():
        setattr(product, field, value)
    product.save()
    return product
