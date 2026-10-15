from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import Mock, patch

from catalog.models import Category, Product, ProductVariant
from catalog.services import ProductGenerationService
from botique_backend.storage import SupabaseStorage


class CatalogApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Dresses', slug='dresses')
        self.product = Product.objects.create(
            category=self.category,
            name='Silk Dress',
            slug='silk-dress',
            description='A lightweight silk dress for evening wear.',
            price_minor=24500,
            status=Product.Status.ACTIVE,
        )
        ProductVariant.objects.create(
            product=self.product, sku='SILK-S', size='S', stock_quantity=2)

    def test_product_list_returns_frontend_shape_and_major_units(self):
        response = self.client.get('/api/products/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['pagination']['total'], 1)
        self.assertEqual(response.json()['data'][0]['price'], 245)
        self.assertEqual(response.json()['data']
                         [0]['variants'][0]['price'], 245)

    def test_product_list_paginates_results(self):
        for index in range(22):
            Product.objects.create(
                category=self.category,
                name=f'Paged dress {index}',
                slug=f'paged-dress-{index}',
                description='Created for storefront pagination coverage.',
                price_minor=12000,
                status=Product.Status.ACTIVE,
            )

        first_page = self.client.get('/api/products/?page=1&limit=10')
        second_page = self.client.get('/api/products/?page=2&limit=10')

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.json()['data']), 10)
        self.assertEqual(first_page.json()['pagination'], {
            'page': 1, 'limit': 10, 'total': 23, 'totalPages': 3,
        })
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.json()['data']), 10)
        self.assertEqual(second_page.json()['pagination']['page'], 2)

    @patch('botique_backend.storage.SupabaseStorage._get_bucket_proxy')
    def test_supabase_storage_upload_uses_string_file_options(self, get_bucket):
        bucket = Mock()
        get_bucket.return_value = bucket
        storage = SupabaseStorage(
            url='https://example.supabase.co', key='test-key')
        image = SimpleUploadedFile(
            'dress.png', b'fake-image', content_type='image/png')

        storage._save('products/dress.png', image)

        bucket.upload.assert_called_once_with(
            'products/dress.png',
            b'fake-image',
            {
                'content-type': 'image/png',
                'cache-control': 'public, max-age=31536000, immutable',
                'upsert': 'true',
            },
        )

    def test_category_list_returns_frontend_shape(self):
        response = self.client.get('/api/categories/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['slug'], 'dresses')
        self.assertIn('imageUrl', response.json()[0])

    def test_draft_products_are_hidden_from_public_list(self):
        self.product.status = Product.Status.DRAFT
        self.product.save(update_fields=['status'])

        response = self.client.get('/api/products/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], [])

    def test_slug_filter_does_not_treat_slug_as_uuid(self):
        response = self.client.get('/api/products/?category=dresses')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['pagination']['total'], 1)

    def test_product_detail_accepts_slug_without_uuid_coercion(self):
        response = self.client.get('/api/products/silk-dress')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['slug'], 'silk-dress')

    def test_empty_json_fields_are_saved_as_empty_lists(self):
        product = Product.objects.create(
            category=self.category,
            name='Minimal Dress',
            slug='minimal-dress',
            description='A minimal dress with optional image metadata.',
            price_minor=18000,
            details=None,
            images=None,
        )

        product.refresh_from_db()
        self.assertEqual(product.details, [])
        self.assertEqual(product.images, [])

    def test_generate_internal_code_is_unique_and_name_based(self):
        first_code = ProductGenerationService.generate_internal_code(
            'Luna Silk Dress')
        ProductVariant.objects.create(product=self.product, sku=first_code)

        second_code = ProductGenerationService.generate_internal_code(
            'Luna Silk Dress')

        self.assertEqual(first_code, 'AT-LUNA-SILK-DRESS')
        self.assertEqual(second_code, 'AT-LUNA-SILK-DRESS-2')

    def test_featured_sort_and_frontend_price_alias_are_supported(self):
        featured = Product.objects.create(
            category=self.category,
            name='Featured Dress',
            slug='featured-dress',
            description='A featured dress for catalog sorting tests.',
            price_minor=12000,
            status=Product.Status.ACTIVE,
            is_featured=True,
        )
        ProductVariant.objects.create(
            product=featured, sku='FEATURED-S', stock_quantity=1)

        response = self.client.get('/api/products/?sort=featured')
        price_response = self.client.get('/api/products/?sort=price:asc')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'][0]['slug'], 'featured-dress')
        self.assertEqual(price_response.status_code, 200)
        self.assertEqual(price_response.json()['data'][0]['price'], 120)
