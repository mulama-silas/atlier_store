"""Catalog tools: search, compare, availability.

Mirrors ``catalog.views.ProductListView`` filtering so the assistant never
sees a product the storefront would hide, and never exposes exact stock
quantities (only available / lowStock booleans).
"""
from django.db.models import Q

from catalog.models import Product

LOW_STOCK_THRESHOLD = 3
MAX_RESULTS = 10

_SALE_FLAGS = {'sale', 'new', 'best_seller', 'featured'}
_SEARCH_SYNONYMS = {
    'shoe': ('shoe', 'shoes', 'footwear', 'sneaker', 'sneakers', 'trainer',
             'trainers', 'heel', 'heels', 'sandal', 'sandals', 'boot',
             'boots', 'loafer', 'loafers'),
    'shoes': ('shoe', 'shoes', 'footwear', 'sneaker', 'sneakers', 'trainer',
              'trainers', 'heel', 'heels', 'sandal', 'sandals', 'boot',
              'boots', 'loafer', 'loafers'),
    'footwear': ('shoe', 'shoes', 'footwear', 'sneaker', 'sneakers', 'trainer',
                 'trainers', 'heel', 'heels', 'sandal', 'sandals', 'boot',
                 'boots', 'loafer', 'loafers'),
}


def _base_queryset():
    return Product.objects.filter(
        status=Product.Status.ACTIVE,
        category__is_active=True,
    ).select_related('category').prefetch_related(
        'variants', 'product_images')


def _price(minor):
    return round((minor or 0) / 100, 2)


def _variants(product):
    return [v for v in product.variants.all() if v.is_active]


def _serialize(product):
    variants = _variants(product)
    images = [img.image_url for img in product.product_images.all()
              if img.image_url]
    if not images:
        images = [u for u in (product.images or []) if isinstance(u, str)]
    stock_values = ([v.stock_quantity for v in variants]
                    if variants else [product.stock_quantity])
    available = any(s > 0 for s in stock_values)
    low_stock = available and any(0 < s <= LOW_STOCK_THRESHOLD for s in stock_values)

    colours, sizes = [], []
    for variant in variants:
        if variant.color and variant.color.lower() not in {c.lower() for c in colours}:
            colours.append(variant.color)
        if variant.size and variant.size not in sizes:
            sizes.append(variant.size)
    if product.color and product.color.lower() not in {c.lower() for c in colours}:
        colours.append(product.color)
    if product.size and product.size not in sizes:
        sizes.append(product.size)

    badges = []
    if product.is_new_arrival:
        badges.append('New')
    if product.is_best_seller:
        badges.append('Best seller')
    if product.is_featured:
        badges.append('Featured')
    if product.compare_at_price_minor:
        badges.append('Sale')

    return {
        'name': product.name,
        'slug': product.slug,
        'price': _price(product.price_minor),
        'compareAtPrice': (_price(product.compare_at_price_minor)
                           if product.compare_at_price_minor else None),
        'category': product.category.name,
        'colours': colours,
        'sizes': sizes,
        'available': available,
        'lowStock': low_stock,
        'badges': badges,
        'image': images[0] if images else '',
        'tagline': product.tagline,
    }


def search_products(*, context=None, query='', colour='', category='',
                    min_price_kes=None, max_price_kes=None, in_stock=True,
                    occasion='', collection='', size='', limit=5):
    products = _base_queryset()

    for term in (query or '').split():
        term = term.strip()
        if term:
            term_matches = Q()
            for variant in _SEARCH_SYNONYMS.get(term.lower(), (term,)):
                term_matches |= (
                    Q(name__icontains=variant)
                    | Q(description__icontains=variant)
                    | Q(tagline__icontains=variant)
                    | Q(category__name__icontains=variant))
            products = products.filter(term_matches)

    for term in (occasion or '').split():
        term = term.strip()
        if term:
            products = products.filter(
                Q(name__icontains=term) | Q(description__icontains=term)
                | Q(tagline__icontains=term))

    if colour:
        products = products.filter(
            Q(color__icontains=colour) | Q(variants__color__icontains=colour))

    if size:
        products = products.filter(
            Q(variants__is_active=True, variants__size__iexact=size)
            | Q(variants__isnull=True, size__iexact=size))

    if category and category.lower() != 'all':
        products = products.filter(
            Q(category__slug__iexact=category) | Q(category__name__icontains=category))

    if isinstance(min_price_kes, int):
        products = products.filter(price_minor__gte=min_price_kes * 100)
    if isinstance(max_price_kes, int):
        products = products.filter(price_minor__lte=max_price_kes * 100)

    collection = (collection or '').strip().lower()
    if collection == 'new':
        products = products.filter(is_new_arrival=True)
    elif collection in ('best_seller', 'bestseller', 'best sellers'):
        products = products.filter(is_best_seller=True)
    elif collection == 'featured':
        products = products.filter(is_featured=True)
    elif collection == 'sale':
        products = products.filter(compare_at_price_minor__isnull=False)

    if in_stock:
        products = products.filter(
            Q(variants__is_active=True, variants__stock_quantity__gt=0)
            | Q(variants__isnull=True, stock_quantity__gt=0))

    products = products.distinct().order_by('-is_featured', '-created_at')
    total = products.count()
    limit = max(1, min(int(limit or 5), MAX_RESULTS))
    results = [_serialize(p) for p in products[:limit]]

    return {'total': total, 'products': results,
            'note': 'Prices in KES. Exact stock is never shown to customers.'}


def compare_products(*, context=None, slugs=None):
    slugs = [s for s in (slugs or []) if isinstance(s, str)][:5]
    if not slugs:
        return {'error': {'code': 'no_products', 'message': 'No products to compare.'}}
    products = _base_queryset().filter(slug__in=slugs)
    by_slug = {p.slug: p for p in products}
    ordered = [by_slug[s] for s in slugs if s in by_slug]
    if not ordered:
        return {'error': {'code': 'not_found', 'message': 'Products not found.'}}
    return {'products': [_serialize(p) for p in ordered]}


def check_variant_availability(*, context=None, product='', size='', colour=''):
    lookup = Q(slug=product)
    products = _base_queryset().filter(lookup)
    if not products.exists():
        products = _base_queryset().filter(name__iexact=product)
    if not products.exists():
        products = _base_queryset().filter(name__icontains=product)[:1]
    target = products.first() if products else None
    if target is None:
        return {'error': {'code': 'not_found',
                          'message': 'Product not found. Search first.'}}

    matches = []
    for variant in _variants(target):
        if size and (variant.size or '').lower() != size.lower():
            continue
        if colour and colour.lower() not in (variant.color or '').lower():
            continue
        stock = variant.stock_quantity
        matches.append({
            'size': variant.size,
            'colour': variant.color,
            'available': stock > 0,
            'lowStock': 0 < stock <= LOW_STOCK_THRESHOLD,
        })

    if not matches:
        stock = target.stock_quantity
        if not size and not colour:
            matches.append({
                'size': target.size,
                'colour': target.color,
                'available': stock > 0,
                'lowStock': 0 < stock <= LOW_STOCK_THRESHOLD,
            })
        else:
            return {
                'product': {'name': target.name, 'slug': target.slug},
                'matches': [],
                'message': 'That size/colour combination is not available.',
                'availableOptions': _serialize(target),
            }

    return {'product': {'name': target.name, 'slug': target.slug},
            'matches': matches}
