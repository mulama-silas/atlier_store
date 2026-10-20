import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

from .models import Category, Product, ProductImage, ProductImportLog


REQUIRED_COLUMNS = {'name', 'price', 'category', 'sku', 'stock_quantity'}

BULK_IMPORT_COLUMNS = [
    'product_code',
    'name',
    'description',
    'tagline',
    'category',
    'status',
    'color',
    'color_hex',
    'size',
    'sku',
    'price',
    'stock',
    'image_1',
    'image_2',
    'image_3',
    'image_4',
]


@dataclass
class ImportRowResult:
    row_number: int
    sku: str = ''
    status: str = 'failed'
    product_id: Optional[str] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class ImportResult:
    rows_total: int = 0
    rows_success: int = 0
    rows_failed: int = 0
    rows: List[ImportRowResult] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    file_name: str = ''

    @property
    def success_rate(self) -> float:
        if self.rows_total <= 0:
            return 0.0
        return round((self.rows_success / self.rows_total) * 100, 2)


class ProductGenerationService:
    """Lightweight local product metadata generation."""

    @staticmethod
    def generate_internal_code(name: str) -> str:
        """Create a short unique internal code for a product variant."""
        from .models import ProductVariant

        base = re.sub(r'[^A-Z0-9]+', '-', (name or '').upper()).strip('-')
        base = (base[:24] or 'PRODUCT').rstrip('-')
        candidate = f'AT-{base}'
        suffix = 1
        while ProductVariant.objects.filter(sku=candidate).exists():
            suffix += 1
            candidate = f'AT-{base[:(78 - len(str(suffix)))]}-{suffix}'
        return candidate[:80]

    @staticmethod
    def _next_unique_slug(base_slug: str) -> str:
        candidate = slugify(base_slug)[:100] or 'product'
        suffix = 2
        while Product.objects.filter(slug=candidate).exists():
            candidate = f'{slugify(base_slug)[:88]}-{suffix}'
            suffix += 1
        return candidate

    @staticmethod
    def generate_product_metadata(name: str) -> Optional[dict]:
        """Build storefront copy and a unique URL slug without any AI service."""
        product_name = (name or '').strip() or 'New Product'
        return {
            'description': (
                f'{product_name} brings refined style, comfortable wear, and considered '
                'craftsmanship to your everyday wardrobe.'
            ),
            'slug': ProductGenerationService._next_unique_slug(product_name),
        }


class BulkImportTemplateService:
    """Generate multi-sheet XLSX template for bulk product import."""

    DATA_COLUMNS = BULK_IMPORT_COLUMNS
    BRAND_DARK = '332A28'
    BRAND_ACCENT = '9B554B'
    BRAND_BLUSH = 'F6ECE8'
    BRAND_PALE = 'FBF8F6'
    GRID = 'E8E1DD'

    INSTRUCTIONS = [
        ('FIELD', 'REQUIRED', 'DESCRIPTION', 'ACCEPTED VALUES / NOTES'),
        ('product_code', 'YES', 'Stable product identifier. All rows with the same product_code are grouped into one product with multiple variants.', 'Alphanumeric, hyphens. Example: LSD001'),
        ('name', 'YES', 'Product name. Must be identical for all rows sharing the same product_code.', 'Text, max 200 chars'),
        ('description', 'NO', 'Full product description.', 'Text'),
        ('tagline', 'NO', 'Short marketing tagline.', 'Text, max 255 chars'),
        ('category', 'YES', 'Category name. Matched against existing categories case-insensitively; categories that do not exist yet are created automatically during import.', 'Category name, e.g., "Dresses" — existing or new'),
        ('status', 'NO', 'Optional spreadsheet status. The status selected on the upload screen is applied to every product.', 'DRAFT, ACTIVE, ARCHIVED'),
        ('color', 'YES', 'Variant color name.', 'Text, e.g., "Black", "Navy Blue"'),
        ('color_hex', 'NO', 'Hex color code for swatches.', '#RRGGBB format, e.g., #000000'),
        ('size', 'YES', 'Variant size.', 'Text, e.g., "S", "M", "L", "32", "One Size"'),
        ('sku', 'YES', 'Unique variant SKU. Must be globally unique across all products.', 'Alphanumeric, hyphens. Example: LSD-BLK-S'),
        ('price', 'YES', 'Price in major currency units (for example, 4500 stores as 450000 minor units and displays as KES 4500.00).', 'Positive number, 2 decimal places max'),
        ('stock', 'YES', 'Available stock quantity. Cannot be negative.', 'Integer >= 0'),
        ('image_1', 'NO', 'Primary image filename from images/ folder.', 'Filename only, e.g., luna-black-1.jpg'),
        ('image_2', 'NO', 'Secondary image filename.', 'Filename only'),
        ('image_3', 'NO', 'Third image filename.', 'Filename only'),
        ('image_4', 'NO', 'Fourth image filename.', 'Filename only'),
        ('package', 'YES', 'ZIP must contain one products.xlsx workbook and an images/ directory. A single containing folder is supported.', 'MODEZA_IMPORT.zip'),
        ('image_naming', 'YES', 'Each image cell contains a filename only, without the images/ prefix.', 'Use the exact filename; JPG, JPEG, PNG and WEBP are supported'),
        ('variant_grouping', 'YES', 'Each worksheet row is one variant. Rows sharing product_code become one parent product.', 'Do not create one product per row'),
        ('stock', 'YES', 'Stock is the absolute quantity for the variant. Re-import updates stock through the existing inventory transaction flow.', 'Integer >= 0; zero is allowed and produces a warning'),
        ('pricing', 'YES', 'Price is the customer-facing amount in major currency units and is converted to minor units by MODEZA.', 'Use values such as 4500 or 4500.00'),
        ('confirmation', 'YES', 'Upload and validation never change the catalog. Review all errors and warnings, then confirm the import.', 'Errors block confirmation by default'),
    ]

    EXAMPLE_ROWS = [
        {
            'product_code': 'LSD001',
            'name': 'Luna Silk Dress',
            'description': 'Elegant silk dress perfect for evening occasions.',
            'tagline': 'Timeless elegance in pure silk',
            'category': 'Dresses',
            'status': 'DRAFT',
            'color': 'Black',
            'color_hex': '#000000',
            'size': 'S',
            'sku': 'LSD-BLK-S',
            'price': '4500',
            'stock': '5',
            'image_1': 'luna-black-1.jpg',
            'image_2': 'luna-black-2.jpg',
            'image_3': '',
            'image_4': '',
        },
        {
            'product_code': 'LSD001',
            'name': 'Luna Silk Dress',
            'description': 'Elegant silk dress perfect for evening occasions.',
            'tagline': 'Timeless elegance in pure silk',
            'category': 'Dresses',
            'status': 'DRAFT',
            'color': 'Black',
            'color_hex': '#000000',
            'size': 'M',
            'sku': 'LSD-BLK-M',
            'price': '4500',
            'stock': '7',
            'image_1': 'luna-black-1.jpg',
            'image_2': 'luna-black-2.jpg',
            'image_3': '',
            'image_4': '',
        },
        {
            'product_code': 'LSD001',
            'name': 'Luna Silk Dress',
            'description': 'Elegant silk dress perfect for evening occasions.',
            'tagline': 'Timeless elegance in pure silk',
            'category': 'Dresses',
            'status': 'DRAFT',
            'color': 'Black',
            'color_hex': '#000000',
            'size': 'L',
            'sku': 'LSD-BLK-L',
            'price': '4500',
            'stock': '0',
            'image_1': 'luna-black-1.jpg',
            'image_2': 'luna-black-2.jpg',
            'image_3': '',
            'image_4': '',
        },
        {
            'product_code': 'LSD001',
            'name': 'Luna Silk Dress',
            'description': 'Elegant silk dress perfect for evening occasions.',
            'tagline': 'Timeless elegance in pure silk',
            'category': 'Dresses',
            'status': 'DRAFT',
            'color': 'Red',
            'color_hex': '#FF0000',
            'size': 'S',
            'sku': 'LSD-RED-S',
            'price': '4600',
            'stock': '3',
            'image_1': 'luna-red-1.jpg',
            'image_2': 'luna-red-2.jpg',
            'image_3': '',
            'image_4': '',
        },
        {
            'product_code': 'LSD001',
            'name': 'Luna Silk Dress',
            'description': 'Elegant silk dress perfect for evening occasions.',
            'tagline': 'Timeless elegance in pure silk',
            'category': 'Dresses',
            'status': 'DRAFT',
            'color': 'Red',
            'color_hex': '#FF0000',
            'size': 'M',
            'sku': 'LSD-RED-M',
            'price': '4600',
            'stock': '0',
            'image_1': 'luna-red-1.jpg',
            'image_2': 'luna-red-2.jpg',
            'image_3': '',
            'image_4': '',
        },
    ]

    @classmethod
    def generate_workbook(cls) -> Workbook:
        """Generate the complete multi-sheet XLSX template."""
        wb = Workbook()
        wb.properties.title = 'MODEZA Boutique - Product Import Template'
        wb.properties.subject = 'Validated product and variant import workbook'
        wb.properties.creator = 'MODEZA Boutique'

        ws_data = wb.active
        ws_data.title = 'Products'
        cls._write_data_sheet(ws_data)

        ws_instructions = wb.create_sheet('Instructions')
        cls._write_instructions_sheet(ws_instructions)

        ws_example = wb.create_sheet('Example')
        cls._write_example_sheet(ws_example)

        ws_categories = wb.create_sheet('Categories')
        cls._write_categories_sheet(ws_categories)

        return wb

    @classmethod
    def _write_data_sheet(cls, ws):
        """Write the main data entry sheet with headers and formatting."""
        header_font = Font(name='Aptos', bold=True, color='FFFFFF', size=10)
        header_fill = PatternFill(start_color=cls.BRAND_DARK, end_color=cls.BRAND_DARK, fill_type='solid')
        header_border = Border(bottom=Side(style='medium', color=cls.BRAND_ACCENT))
        widths = {
            'product_code': 18, 'name': 28, 'description': 42, 'tagline': 30,
            'category': 20, 'status': 15, 'color': 18, 'color_hex': 14,
            'size': 14, 'sku': 20, 'price': 16, 'stock': 14,
            'image_1': 25, 'image_2': 25, 'image_3': 25, 'image_4': 25,
        }

        for col_idx, col_name in enumerate(cls.DATA_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = header_border
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            cell.comment = Comment(
                next((row[2] for row in cls.INSTRUCTIONS[1:] if row[0] == col_name),
                     'Optional product import field.'),
                'MODEZA Boutique',
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(col_name, max(15, len(col_name) + 5))

        ws.row_dimensions[1].height = 34
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = cls.BRAND_ACCENT
        ws.auto_filter.ref = f'A1:{get_column_letter(len(cls.DATA_COLUMNS))}1000'
        ws.sheet_view.zoomScale = 85

        required_columns = {'product_code', 'name', 'category', 'color', 'size', 'sku', 'price', 'stock'}
        for col_idx, col_name in enumerate(cls.DATA_COLUMNS, start=1):
            for row_idx in range(2, 102):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.fill = PatternFill(
                    fill_type='solid',
                    fgColor=cls.BRAND_PALE if row_idx % 2 == 0 else 'FFFFFF',
                )
                if col_name in required_columns:
                    cell.border = Border(bottom=Side(style='hair', color=cls.GRID))
            if col_name == 'price':
                for row_idx in range(2, 5001):
                    ws.cell(row=row_idx, column=col_idx).number_format = '#,##0.00'
            elif col_name == 'stock':
                for row_idx in range(2, 5001):
                    ws.cell(row=row_idx, column=col_idx).number_format = '0'

        status_column = get_column_letter(cls.DATA_COLUMNS.index('status') + 1)
        status_validation = DataValidation(type='list', formula1='"DRAFT,ACTIVE,ARCHIVED"', allow_blank=True)
        status_validation.error = 'Choose DRAFT, ACTIVE, or ARCHIVED.'
        status_validation.errorTitle = 'Unknown product status'
        status_validation.prompt = 'Leave blank to use the status chosen on the upload page.'
        status_validation.promptTitle = 'Optional status override'
        ws.add_data_validation(status_validation)
        status_validation.add(f'{status_column}2:{status_column}5000')

        price_column = get_column_letter(cls.DATA_COLUMNS.index('price') + 1)
        price_validation = DataValidation(type='decimal', operator='greaterThan', formula1='0', allow_blank=False)
        price_validation.error = 'Enter a price greater than zero, with no more than two decimal places.'
        price_validation.errorTitle = 'Check the price'
        ws.add_data_validation(price_validation)
        price_validation.add(f'{price_column}2:{price_column}5000')

        stock_column = get_column_letter(cls.DATA_COLUMNS.index('stock') + 1)
        stock_validation = DataValidation(type='whole', operator='greaterThanOrEqual', formula1='0', allow_blank=False)
        stock_validation.error = 'Enter a whole number of zero or more.'
        stock_validation.errorTitle = 'Check the stock quantity'
        ws.add_data_validation(stock_validation)
        stock_validation.add(f'{stock_column}2:{stock_column}5000')

        ws.freeze_panes = 'A2'

    @classmethod
    def _write_instructions_sheet(cls, ws):
        """Write the instructions sheet."""
        header_font = Font(name='Aptos', bold=True, color='FFFFFF', size=10)
        header_fill = PatternFill(start_color=cls.BRAND_DARK, end_color=cls.BRAND_DARK, fill_type='solid')

        for col_idx, header in enumerate(cls.INSTRUCTIONS[0], start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = [25, 12, 60, 40][col_idx - 1]
        ws.row_dimensions[1].height = 28

        for row_idx, row_data in enumerate(cls.INSTRUCTIONS[1:], start=2):
            for col_idx, value in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.alignment = Alignment(wrap_text=True, vertical='top')
                cell.fill = PatternFill(fill_type='solid', fgColor=cls.BRAND_PALE if row_idx % 2 == 0 else 'FFFFFF')
                cell.border = Border(bottom=Side(style='hair', color=cls.GRID))
            ws.row_dimensions[row_idx].height = 54

        ws.freeze_panes = 'A2'
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = 'C08D64'
        ws.auto_filter.ref = f'A1:D{len(cls.INSTRUCTIONS)}'
        ws.sheet_view.zoomScale = 90

    @classmethod
    def _write_example_sheet(cls, ws):
        """Write the example sheet with sample data."""
        widths = {
            'product_code': 18, 'name': 28, 'description': 42, 'tagline': 30,
            'category': 20, 'status': 15, 'color': 18, 'color_hex': 14,
            'size': 14, 'sku': 20, 'price': 16, 'stock': 14,
            'image_1': 25, 'image_2': 25, 'image_3': 25, 'image_4': 25,
        }
        header_font = Font(name='Aptos', bold=True, color='FFFFFF', size=10)
        header_fill = PatternFill(start_color=cls.BRAND_ACCENT, end_color=cls.BRAND_ACCENT, fill_type='solid')
        example_fill = PatternFill(start_color=cls.BRAND_BLUSH, end_color=cls.BRAND_BLUSH, fill_type='solid')

        for col_idx, col_name in enumerate(cls.DATA_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(col_name, max(15, len(col_name) + 5))

        for row_idx, row_data in enumerate(cls.EXAMPLE_ROWS, start=2):
            for col_idx, col_name in enumerate(cls.DATA_COLUMNS, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=row_data.get(col_name, ''))
                cell.fill = example_fill
                cell.alignment = Alignment(wrap_text=True)

        ws.freeze_panes = 'A2'
        ws.row_dimensions[1].height = 34
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = 'D39A8E'
        ws.auto_filter.ref = f'A1:{get_column_letter(len(cls.DATA_COLUMNS))}{len(cls.EXAMPLE_ROWS) + 1}'
        ws.sheet_view.zoomScale = 85

    @classmethod
    def _write_categories_sheet(cls, ws):
        """Write the categories reference sheet (populated from database)."""
        header_font = Font(name='Aptos', bold=True, color='FFFFFF', size=10)
        header_fill = PatternFill(start_color=cls.BRAND_DARK, end_color=cls.BRAND_DARK, fill_type='solid')

        headers = ['Category Name', 'Slug', 'Description', 'Active']
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = [30, 30, 50, 10][col_idx - 1]

        categories = Category.objects.filter(is_active=True).order_by('name')
        for row_idx, cat in enumerate(categories, start=2):
            ws.cell(row=row_idx, column=1, value=cat.name)
            ws.cell(row=row_idx, column=2, value=cat.slug)
            ws.cell(row=row_idx, column=3, value=cat.description)
            ws.cell(row=row_idx, column=4, value='Yes' if cat.is_active else 'No')

        ws.freeze_panes = 'A2'
        ws.row_dimensions[1].height = 28
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = '78836F'
        ws.auto_filter.ref = f'A1:D{max(1, Category.objects.filter(is_active=True).count() + 1)}'

    @classmethod
    def to_bytes(cls) -> bytes:
        """Generate workbook and return as bytes."""
        wb = cls.generate_workbook()
        from io import BytesIO
        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()


class ProductImportService:
    """Reusable bulk import service for product catalog data."""

    @staticmethod
    def normalize_sku(value: str) -> str:
        value = (value or '').strip().upper()
        value = re.sub(r'[^A-Z0-9]+', '-', value)
        value = re.sub(r'-+', '-', value).strip('-')
        return value

    @staticmethod
    def normalize_file_prefix(value: str) -> str:
        normalized = (value or '').strip().lower()
        normalized = unicodedata.normalize('NFKD', normalized)
        normalized = ''.join(
            c for c in normalized if not unicodedata.combining(c))
        normalized = re.sub(r'[^a-z0-9]+', '-', normalized)
        normalized = re.sub(r'-+', '-', normalized).strip('-')
        return normalized

    @staticmethod
    def parse_file(file) -> Tuple[List[dict], Optional[str]]:
        """Return rows and optional error message from a CSV or XLSX upload."""
        file_name = getattr(file, 'name', '') or 'import-file'
        file_bytes = file.read()
        if file_name.lower().endswith('.csv'):
            text = file_bytes.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                return [], 'The uploaded file has no header row.'
            rows = list(reader)
            return rows, None

        if file_name.lower().endswith(('.xlsx', '.xls')):
            try:
                workbook = load_workbook(filename=io.BytesIO(
                    file_bytes), read_only=True, data_only=True)
                sheet = workbook.active
                rows = []
                headers = [cell.value for cell in next(
                    sheet.iter_rows(min_row=1, max_row=1))]
                for row in sheet.iter_rows(min_row=2, values_only=True):
                    row_dict = dict(zip(headers, row))
                    rows.append(row_dict)
                return rows, None
            except Exception as exc:
                return [], f'Unable to parse XLSX file: {exc}'

        return [], 'Unsupported file type. Please upload CSV or XLSX.'

    @staticmethod
    def validate_columns(headers: Sequence[str]) -> List[str]:
        normalized_headers = {str(h).strip().lower()
                              for h in headers if h is not None}
        missing = sorted(REQUIRED_COLUMNS.difference(normalized_headers))
        return missing

    @staticmethod
    def determine_category(value: str):
        value = (value or '').strip()
        if not value:
            return None, 'category is required'
        category_obj = Category.objects.filter(slug=slugify(value)).first()
        if category_obj is None:
            category_obj = Category.objects.filter(name__iexact=value).first()
        if category_obj is None:
            # Create a fallback category for the imported data.
            try:
                category_obj = Category.objects.create(
                    name=value.title(),
                    slug=slugify(value),
                    description='Created automatically from bulk product import.',
                    is_active=True,
                )
            except Exception:
                return None, 'category could not be created'
        return category_obj, None

    @staticmethod
    def attach_images_by_sku(product: Product, sku: str, image_files: Optional[Iterable]) -> None:
        if not image_files:
            return

        sku_prefix = ProductImportService.normalize_file_prefix(sku)
        sku_parts = set(re.findall(r'[a-z0-9]+', sku_prefix))
        if not sku_parts:
            return

        selected = []
        for idx, image in enumerate(image_files or []):
            file_name = getattr(image, 'name', '') or ''
            file_prefix = ProductImportService.normalize_file_prefix(file_name)
            merged = re.findall(r'[a-z0-9]+', file_prefix)
            match = any(part in merged for part in sku_parts)
            if match:
                selected.append(image)

        for order, image_file in enumerate(selected, start=1):
            filename = getattr(image_file, 'name',
                               '') or f'import-image-{order}.jpg'
            saved_path = default_storage.save(
                f'products/{slugify(filename)}', image_file)
            image_url = default_storage.url(saved_path)
            ProductImage.objects.update_or_create(
                product=product,
                variant=None,
                image=image_url,
                defaults={
                    'is_primary': order == 1,
                    'order': order,
                },
            )

    @staticmethod
    @transaction.atomic
    def import_products_from_file(file, image_files=None, created_by=None) -> ImportResult:
        """
        Import product rows from a CSV or XLSX file with per-row validation.
        Returns a structured ImportResult containing all row outcomes.
        """
        image_files = list(image_files or [])
        rows, parse_error = ProductImportService.parse_file(file)
        results = ImportResult(file_name=getattr(file, 'name', ''))
        if parse_error:
            results.messages.append(parse_error)
            return results

        if not rows:
            results.messages.append('No rows found in the import file.')
            return results

        # Normalize headers from file. This remains tolerant of spacing/casing.
        headers = list(rows[0].keys()) if rows else []
        required_missing = ProductImportService.validate_columns(headers)
        if required_missing:
            results.messages.append(
                'Missing required columns: ' + ', '.join(required_missing))
            return results

        results.rows_total = len(rows)
        # Keep counter lines not abort batch.
        for row_index, row in enumerate(rows, start=2):
            row_result = ImportRowResult(row_number=row_index)
            raw = {str(k).strip().lower(): str(v).strip() if isinstance(
                v, str) else v for k, v in row.items()}
            # Map common input names.
            sku = (raw.get('sku') or '').strip()
            name = (raw.get('name') or '').strip()
            price = (raw.get('price') or '').strip()
            category = (raw.get('category') or '').strip()
            stock_quantity = (raw.get('stock_quantity') or '').strip()
            description = (raw.get('description') or '').strip()
            size = (raw.get('size') or '').strip()
            color = (raw.get('color') or '').strip()
            is_active = str(raw.get('is_active') or 'true').strip().lower() in {
                '1', 'true', 'yes', 'y'}

            errors = []
            if not name:
                errors.append('name is required')
            if not sku:
                errors.append('sku is required')
            else:
                normalized_sku = ProductImportService.normalize_sku(sku)
                if not re.fullmatch(r'^[A-Z0-9][A-Z0-9\-]{1,79}$', normalized_sku):
                    errors.append('sku format is invalid')
                sku = normalized_sku
            if not category:
                errors.append('category is required')
            if not price:
                errors.append('price is required')
            else:
                try:
                    price_amount = float(price)
                    if price_amount <= 0:
                        errors.append('price must be greater than 0')
                except Exception:
                    errors.append('price must be a number')
            if stock_quantity == '':
                errors.append('stock_quantity is required')
            else:
                try:
                    stock_int = int(stock_quantity)
                    if stock_int < 0:
                        errors.append('stock_quantity must be >= 0')
                except Exception:
                    errors.append('stock_quantity must be an integer')

            if errors:
                row_result.errors = errors
                results.rows.append(row_result)
                results.rows_failed += 1
                continue

            # Determine category and create if necessary.
            category_obj, category_error = ProductImportService.determine_category(
                category)
            if category_error:
                errors.append(category_error)
                row_result.errors = errors
                results.rows.append(row_result)
                results.rows_failed += 1
                continue

            slug_value = f"{slugify(name)}-{slugify(sku)}"

            # Convert file price to minor units, assuming two decimal places.
            price_minor = int(round(float(price) * 100))
            # Validate SKU and save.
            product_defaults = {
                'name': name,
                'description': description,
                'price_minor': price_minor,
                'category': category_obj,
                'size': size,
                'color': color,
                'stock_quantity': int(stock_quantity),
                'status': Product.Status.ACTIVE,
                'is_active': is_active,
                'slug': slug_value,
                'sku': sku,
            }
            product, created = Product.objects.update_or_create(
                sku=sku,
                defaults=product_defaults,
            )
            product.stock_quantity = int(stock_quantity)
            product.name = name
            product.description = description or product.description
            product.price_minor = price_minor
            product.category = category_obj
            product.size = size
            product.color = color
            product.is_active = is_active
            product.status = Product.Status.ACTIVE
            product.slug = slug_value or product.slug or slugify(name)
            product.save(update_fields=[
                'name', 'description', 'price_minor', 'category', 'size', 'color',
                'stock_quantity', 'status', 'is_active', 'slug', 'sku', 'images', 'updated_at'
            ])

            # Associate any image file whose file name contains the SKU prefix or normalized token.
            ProductImportService.attach_images_by_sku(
                product, sku, image_files)

            row_result.row_number = row_index
            row_result.status = 'success'
            row_result.sku = sku
            row_result.product_id = str(product.id)
            results.rows.append(row_result)
            results.rows_success += 1

        # Always create an audit log for this run.
        ProductImportLog.objects.create(
            filename=getattr(file, 'name', ''),
            rows_total=results.rows_total,
            rows_success=results.rows_success,
            rows_failed=results.rows_failed,
            error_details={
                'rows': [
                    {
                        'row_number': row.row_number,
                        'sku': row.sku,
                        'status': row.status,
                        'product_id': row.product_id,
                        'errors': row.errors,
                    }
                    for row in results.rows
                ],
                'messages': results.messages,
            },
            created_by=created_by,
        )

        return results


def import_products_from_file(file, image_files=None, created_by=None):
    return ProductImportService.import_products_from_file(
        file,
        image_files,
        created_by,
    )
