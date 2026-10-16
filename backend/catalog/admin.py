import csv
import io

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import path

from .models import Category, Product, ProductImportLog, ProductReview, ProductVariant
from .services import import_products_from_file


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ('sku', 'size', 'color', 'color_hex',
              'price_minor', 'stock_quantity', 'is_active')


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'rating', 'created_at')
    search_fields = ('product__name', 'user__email', 'title', 'body')
    readonly_fields = ('product', 'user', 'rating', 'title', 'body', 'created_at', 'updated_at')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'status', 'price_minor',
                    'stock_total', 'is_featured', 'updated_at')
    list_filter = ('status', 'category', 'is_featured',
                   'is_new_arrival', 'is_best_seller')
    search_fields = ('name', 'slug', 'description', 'variants__sku')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')
    inlines = (ProductVariantInline,)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import/', self.admin_site.admin_view(self.import_products_view),
                 name='catalog_product_import'),
            path('download-template/', self.admin_site.admin_view(self.download_template_view),
                 name='catalog_product_download_template'),
        ]
        return custom_urls + urls

    def import_products_view(self, request):
        from django.template.response import TemplateResponse

        if not request.user.is_staff or not request.user.is_superuser:
            raise PermissionDenied('Staff/superuser permission required.')

        result = None
        if request.method == 'POST':
            file = request.FILES.get('file')
            image_files = request.FILES.getlist('image_files')
            if not file:
                messages.error(request, 'Please upload a CSV/XLSX file.')
            else:
                result = import_products_from_file(
                    file, image_files, created_by=request.user)
                messages.success(
                    request, f'Import complete: {result.rows_success} rows succeeded, {result.rows_failed} failed.')

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Bulk Product Import',
            'result': result,
            'has_view_permission': self.has_view_permission(request),
            'has_module_permission': self.has_module_permission(request),
            'media': self.media,
        }
        return TemplateResponse(request, 'catalog/admin/product_import_admin.html', context)

    def download_template_view(self, request):
        if not request.user.is_staff or not request.user.is_superuser:
            raise PermissionDenied('Staff/superuser permission required.')

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['name', 'price', 'category', 'sku',
                        'stock_quantity', 'description', 'size', 'color', 'is_active'])
        writer.writerow(['Silk Wrap Dress', '2450', 'Dresses', 'SKU-DRESS-001',
                        '10', 'Soft silk wrap dress', 'M', 'Ivory', 'true'])
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="product_import_template.csv"'
        return response

    @admin.display(description='Stock')
    def stock_total(self, obj):
        return sum(variant.stock_quantity for variant in obj.variants.all())


@admin.register(ProductImportLog)
class ProductImportLogAdmin(admin.ModelAdmin):
    list_display = ('filename', 'rows_total', 'rows_success',
                    'rows_failed', 'created_by', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('filename', 'created_by__username')
    readonly_fields = ('filename', 'rows_total', 'rows_success',
                       'rows_failed', 'error_details', 'created_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'size', 'color',
                    'price_minor', 'stock_quantity', 'is_active')
    list_filter = ('is_active', 'product__category')
    search_fields = ('sku', 'product__name', 'color', 'size')
