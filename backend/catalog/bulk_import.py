import hashlib
import io
import logging
import re
import shutil
import stat
import tempfile
import zipfile
from collections import OrderedDict, defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from openpyxl import load_workbook
from PIL import Image, UnidentifiedImageError

from admin_ui.models import notify_staff
from audit.services import AuditLogService
from catalog.models import Category, ImportJob, Product, ProductImage, ProductVariant
from catalog.variant_services import normalize_hex, normalize_sku
from inventory.models import InventoryTransaction

logger = logging.getLogger('catalog.bulk_import')


def _temporary_import_root():
    return Path(getattr(settings, 'BASE_DIR', tempfile.gettempdir())) / '.private_bulk_imports'


def _temporary_package_path(job_id):
    return _temporary_import_root() / str(job_id) / 'package.zip'


def _delete_temporary_import(job_id):
    shutil.rmtree(_temporary_import_root() / str(job_id), ignore_errors=True)


def is_temporary_import_path(path):
    if not path:
        return False
    return Path(path).resolve().is_relative_to(_temporary_import_root().resolve())

REQUIRED_COLUMNS = {
    'product_code',
    'name',
    'category',
    'color',
    'size',
    'sku',
    'price',
    'stock',
}
PRODUCT_FIELDS = ('name', 'description', 'tagline', 'category')
IMAGE_FIELDS = ('image_1', 'image_2', 'image_3', 'image_4')
ALLOWED_IMAGE_FORMATS = {
    '.jpg': 'JPEG',
    '.jpeg': 'JPEG',
    '.png': 'PNG',
    '.webp': 'WEBP',
}
HEADER_ALIASES = {
    'productcode': 'product_code',
    'product_code': 'product_code',
    'stock_quantity': 'stock',
    'stockquantity': 'stock',
    'colour': 'color',
    'color_hex': 'color_hex',
    'image1': 'image_1',
    'image2': 'image_2',
    'image3': 'image_3',
    'image4': 'image_4',
}


class BulkImportError(Exception):
    pass


class BulkImportPackageError(BulkImportError):
    pass


class BulkImportConflict(BulkImportError):
    pass


def queue_import_outcome_email(email_type, job, headline, detail=''):
    """Queue the operator-facing email for a bulk import outcome.

    Sent to the single ops inbox — ``notify_staff`` already fans the same event
    out in-app. ``related_import_job`` supplies the idempotency key, so a
    replayed completion or a duplicated task cannot email twice.
    """
    from emails.services import queue_email

    origin = setting('FRONTEND_ORIGIN', 'http://localhost:3000')
    report_url = f'{origin}/admin/dashboard/products/import/{job.pk}/report/'
    lines = [headline, '']
    if detail:
        lines += [detail, '']
    lines += [
        f'File: {job.filename}',
        f'Products created: {job.created_products}',
        f'Products updated: {job.updated_products}',
        f'Variants created: {job.created_variants}',
        f'Variants updated: {job.updated_variants}',
        f'Images uploaded: {job.uploaded_images}',
        f'Rows failed: {job.failed_rows}',
        f'Warnings: {job.warning_count}',
        '',
        f'View the report: {report_url}',
    ]
    return queue_email(
        email_type=email_type,
        subject=f'Bulk import: {job.filename}',
        body_text='\n'.join(lines),
        related_import_job=job,
        metadata={'import_job_id': str(job.pk), 'report_url': report_url},
    )


def setting(name, default):
    return getattr(settings, name, default)


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, Decimal):
        return format(value, 'f')
    return str(value).strip()


def normalize_header(value):
    value = _text(value).lower()
    value = re.sub(r'[^a-z0-9]+', '_', value).strip('_')
    return HEADER_ALIASES.get(value, value)


def _money_to_minor(value):
    try:
        amount = Decimal(_text(value))
    except (InvalidOperation, ValueError):
        raise ValueError('price must be a number')
    if not amount.is_finite() or amount <= 0:
        raise ValueError('price must be greater than 0')
    if amount.as_tuple().exponent < -2:
        raise ValueError('price must have at most 2 decimal places')
    return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _stock_value(value):
    text = _text(value)
    if not text:
        raise ValueError('stock is required')
    if not re.fullmatch(r'\d+', text):
        raise ValueError('stock must be a non-negative integer')
    number = int(text)
    if number > 2_147_483_647:
        raise ValueError('stock is too large')
    return number


def _safe_member_name(filename):
    value = _text(filename).replace('\\', '/')
    if not value or value.startswith('/') or re.match(r'^[A-Za-z]:', value) or '\x00' in value:
        raise BulkImportPackageError('Archive contains an unsafe path.')
    path = PurePosixPath(value)
    if '..' in path.parts or path.is_absolute():
        raise BulkImportPackageError('Archive contains a path traversal entry.')
    if len(path.parts) > 12:
        raise BulkImportPackageError('Archive contains an excessively nested path.')
    return '/'.join(part for part in path.parts if part not in ('', '.'))


def _is_symlink(info):
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


class BulkImportPackage:
    def __init__(self, job):
        self.job = job
        self._file = None
        self._zip = None
        self.members = {}
        self.image_members = OrderedDict()
        self.errors = []
        self.warnings = []

    def __enter__(self):
        if not self.job.package_path:
            raise BulkImportPackageError('The uploaded package is no longer available.')
        try:
            package_path = Path(self.job.package_path)
            if package_path.is_absolute():
                self._file = package_path.open('rb')
            else:
                # Keep existing jobs created before local ZIP storage working.
                self._file = default_storage.open(self.job.package_path, 'rb')
            self._zip = zipfile.ZipFile(self._file, 'r')
            self._inspect()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._zip is not None:
            self._zip.close()
        if self._file is not None:
            self._file.close()
        self._zip = None
        self._file = None

    def _inspect(self):
        max_archive = int(setting('BULK_IMPORT_MAX_ZIP_BYTES', 500 * 1024 * 1024))
        max_total = int(setting('BULK_IMPORT_MAX_EXTRACTED_BYTES', 500 * 1024 * 1024))
        max_entry = int(setting('BULK_IMPORT_MAX_ENTRY_BYTES', 25 * 1024 * 1024))
        max_images = int(setting('BULK_IMPORT_MAX_IMAGES', 10000))
        max_depth = int(setting('BULK_IMPORT_MAX_PATH_DEPTH', 12))
        total_size = 0
        image_count = 0
        has_images_dir = False
        has_excel = False
        seen_names = set()

        for info in self._zip.infolist():
            try:
                name = _safe_member_name(info.filename)
            except BulkImportPackageError as exc:
                self.errors.append(_issue('error', 'archive', str(exc)))
                continue
            if not name:
                continue
            if _is_symlink(info):
                self.errors.append(_issue('error', 'archive', 'Archive symbolic links are not allowed.'))
                continue
            if info.flag_bits & 0x1:
                self.errors.append(_issue('error', 'archive', 'Encrypted archive entries are not allowed.'))
                continue
            if name in seen_names:
                self.errors.append(_issue('error', 'archive', f'Duplicate archive entry: {name}.'))
                continue
            seen_names.add(name)
            if len(PurePosixPath(name).parts) > max_depth:
                self.errors.append(_issue('error', 'archive', f'Archive path is too deeply nested: {name}.'))
                continue
            if info.is_dir() or name.endswith('/'):
                if name == 'images':
                    has_images_dir = True
                continue
            if info.file_size < 0 or info.file_size > max_entry:
                self.errors.append(_issue('error', 'archive', f'Archive entry is too large: {name}.'))
                continue
            total_size += info.file_size
            if total_size > max_total:
                self.errors.append(_issue('error', 'archive', 'Archive expands beyond the allowed size.'))
                break
            if name.lower() == 'products.xlsx':
                has_excel = True
                self.members[name] = info
                continue
            if name == 'images' or name.startswith('images/'):
                has_images_dir = True
                image_count += 1
                if image_count > max_images:
                    self.errors.append(_issue('error', 'archive', 'Archive contains too many image files.'))
                    break
                suffix = PurePosixPath(name).suffix.lower()
                if suffix not in ALLOWED_IMAGE_FORMATS:
                    self.warnings.append(_issue('warning', 'archive', f'Ignored unsupported file in images/: {name}.'))
                    continue
                self.image_members[name] = info
                self.members[name] = info
                continue
            self.warnings.append(_issue('warning', 'archive', f'Ignored unexpected archive file: {name}.'))

        archive_size = self.job.package_size or 0
        if archive_size > max_archive:
            self.errors.append(_issue('error', 'archive', 'ZIP file exceeds the maximum upload size.'))
        if archive_size and total_size > archive_size * 1000 and total_size > 100 * 1024 * 1024:
            self.errors.append(_issue('error', 'archive', 'Archive expansion ratio is unsafe.'))
        if not has_excel:
            self.errors.append(_issue('error', 'archive', 'The package must contain products.xlsx at its root.'))
        if not has_images_dir:
            self.errors.append(_issue('error', 'archive', 'The package must contain an images/ directory.'))
        if not self.image_members:
            self.warnings.append({'field': 'archive', 'message': 'The images/ directory is empty.'})

    def read(self, name, max_bytes=None):
        info = self.members.get(name)
        if info is None:
            raise BulkImportPackageError(f'Archive member not found: {name}.')
        limit = max_bytes or int(setting('BULK_IMPORT_MAX_ENTRY_BYTES', 25 * 1024 * 1024))
        if info.file_size > limit:
            raise BulkImportPackageError(f'Archive member is too large: {name}.')
        data = self._zip.read(info)
        if len(data) > limit:
            raise BulkImportPackageError(f'Archive member is too large: {name}.')
        return data

    def read_excel(self):
        candidates = [name for name in self.members if name.lower() == 'products.xlsx']
        if not candidates:
            raise BulkImportPackageError('The package must contain products.xlsx at its root.')
        return self.read(candidates[0])


def _issue(level, field, message, row_number=None):
    result = {'level': level, 'field': field, 'message': message}
    if row_number is not None:
        result['row_number'] = row_number
    return result


def _image_metadata(data, filename):
    suffix = PurePosixPath(filename).suffix.lower()
    expected_format = ALLOWED_IMAGE_FORMATS.get(suffix)
    if not expected_format:
        raise BulkImportError(f'Unsupported image format: {filename}.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or '').upper()
            width, height = image.size
            if width < 1 or height < 1:
                raise BulkImportError(f'Image has invalid dimensions: {filename}.')
            max_dimension = int(setting('BULK_IMPORT_MAX_IMAGE_DIMENSION', 8000))
            max_pixels = int(setting('BULK_IMPORT_MAX_IMAGE_PIXELS', 40_000_000))
            if max(width, height) > max_dimension or width * height > max_pixels:
                raise BulkImportError(f'Image dimensions are too large: {filename}.')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except BulkImportError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError):
        raise BulkImportError(f'Image cannot be decoded: {filename}.')
    if image_format != expected_format:
        raise BulkImportError(f'Image format does not match its extension: {filename}.')
    return {
        'filename': filename,
        'format': image_format,
        'mime_type': Image.MIME.get(image_format, 'application/octet-stream'),
        'width': width,
        'height': height,
        'size': len(data),
    }


def _read_workbook(data):
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise BulkImportPackageError('products.xlsx could not be read.') from exc
    if 'Products' not in workbook.sheetnames:
        workbook.close()
        raise BulkImportPackageError('The workbook must contain a Products worksheet.')
    sheet = workbook['Products']
    iterator = sheet.iter_rows(values_only=True)
    try:
        header_values = next(iterator)
    except StopIteration as exc:
        workbook.close()
        raise BulkImportPackageError('The Products worksheet has no header row.') from exc
    headers = [normalize_header(value) for value in header_values]
    if not headers or not any(headers):
        workbook.close()
        raise BulkImportPackageError('The Products worksheet has no header row.')
    populated_headers = [header for header in headers if header]
    if len(populated_headers) != len(set(populated_headers)):
        workbook.close()
        raise BulkImportPackageError('The Products worksheet contains duplicate columns.')
    missing = sorted(REQUIRED_COLUMNS.difference(headers))
    if missing:
        workbook.close()
        raise BulkImportPackageError('Missing required columns: ' + ', '.join(missing) + '.')
    rows = []
    max_rows = int(setting('BULK_IMPORT_MAX_ROWS', 10000))
    for row_number, values in enumerate(iterator, start=2):
        row = {header: _text(values[index]) if index < len(values) else '' for index, header in enumerate(headers) if header}
        if not any(row.values()):
            continue
        if len(rows) >= max_rows:
            workbook.close()
            raise BulkImportPackageError(f'The workbook exceeds the maximum of {max_rows} data rows.')
        row['_row_number'] = row_number
        rows.append(row)
    workbook.close()
    if not rows:
        raise BulkImportPackageError('The Products worksheet contains no data rows.')
    return rows


def _category_map():
    categories = Category.objects.filter(is_active=True).only('id', 'name', 'slug')
    by_name = {}
    by_slug = {}
    for category in categories:
        by_name[category.name.casefold()] = category
        by_slug[category.slug.casefold()] = category
    return by_name, by_slug


def _product_slug(name, product_code, current=None):
    if current:
        return current
    from catalog.services import ProductGenerationService
    return ProductGenerationService._next_unique_slug(f'{name}-{product_code}')


class BulkImportValidationService:
    @classmethod
    def validate(cls, job):
        errors = []
        warnings = []
        rows = []
        image_cache = {}
        try:
            with BulkImportPackage(job) as package:
                errors.extend(package.errors)
                warnings.extend(package.warnings)
                if not package.members or any(issue['field'] == 'archive' and issue['level'] == 'error' for issue in errors):
                    return cls._finish(job, rows, errors, warnings, 0, 0, 0)
                rows = _read_workbook(package.read_excel())
                for row in rows:
                    row['_image_names'] = []
                    for field in IMAGE_FIELDS:
                        value = _text(row.get(field))
                        if not value:
                            continue
                        if any(existing.casefold() == value.casefold() for existing in row['_image_names']):
                            warnings.append(_issue('warning', field, 'Image is referenced more than once on this row.', row['_row_number']))
                        if value in image_cache:
                            image_result = image_cache[value]
                        else:
                            image_member = cls._find_image_member(package, value)
                            if image_member is None:
                                image_result = {'error': f'Image "{value}" was referenced but was not found.'}
                            else:
                                try:
                                    image_data = package.read(image_member, int(setting('BULK_IMPORT_MAX_IMAGE_BYTES', 10 * 1024 * 1024)))
                                    image_result = _image_metadata(image_data, image_member)
                                except BulkImportError as exc:
                                    image_result = {'error': str(exc)}
                            image_cache[value] = image_result
                        row['_image_names'].append(value)
                        if image_result.get('error'):
                            errors.append(_issue('error', field, image_result['error'], row['_row_number']))
        except BulkImportError as exc:
            errors.append(_issue('error', 'archive', str(exc)))
            return cls._finish(job, rows, errors, warnings, 0, 0, 0)
        except Exception:
            logger.exception('Bulk import package validation failed for job %s', job.pk)
            errors.append(_issue('error', 'archive', 'The import package could not be validated.'))
            return cls._finish(job, rows, errors, warnings, 0, 0, 0)

        categories_by_name, categories_by_slug = _category_map()
        existing_products = {}
        existing_variants = {}
        groups = OrderedDict()
        seen_skus = defaultdict(list)
        seen_combinations = defaultdict(list)

        for row in rows:
            row_number = row['_row_number']
            code = normalize_sku(row.get('product_code'))
            if not code:
                errors.append(_issue('error', 'product_code', 'product_code is required.', row_number))
            elif len(code) > 80:
                errors.append(_issue('error', 'product_code', 'product_code must be 80 characters or fewer.', row_number))
            row['_product_code'] = code
            row['_sku_raw'] = _text(row.get('sku'))
            sku = normalize_sku(row.get('sku'))
            row['_sku'] = sku
            if not sku:
                errors.append(_issue('error', 'sku', 'sku is required.', row_number))
            elif len(sku) > 80:
                errors.append(_issue('error', 'sku', 'sku must be 80 characters or fewer.', row_number))
            elif row['_sku_raw'].upper() != sku:
                warnings.append(_issue('warning', 'sku', f'SKU was normalized to {sku}.', row_number))
            if sku:
                seen_skus[sku.casefold()].append(row_number)
            for field in ('name', 'category', 'color', 'size'):
                value = _text(row.get(field))
                if not value:
                    errors.append(_issue('error', field, f'{field} is required.', row_number))
                maximum = {'name': 200, 'category': 120, 'color': 80, 'size': 40}.get(field)
                if maximum and len(value) > maximum:
                    errors.append(_issue('error', field, f'{field} must be {maximum} characters or fewer.', row_number))
            if not code:
                continue
            group = groups.setdefault(code, {
                'product_code': code,
                'rows': [],
                'product': {},
                'errors': [],
                'warnings': [],
            })
            group['rows'].append(row)
            for field in PRODUCT_FIELDS:
                value = _text(row.get(field))
                if not value:
                    continue
                previous = group['product'].get(field)
                if previous and previous.casefold() != value.casefold():
                    message = f'Conflicting {field} values for product_code {code}.'
                    errors.append(_issue('error', field, message, row_number))
                    group['errors'].append(_issue('error', field, message))
                elif not previous:
                    group['product'][field] = value
            if len(_text(row.get('tagline'))) > 255:
                errors.append(_issue('error', 'tagline', 'tagline must be 255 characters or fewer.', row_number))
            if not _text(row.get('description')):
                group['warnings'].append(_issue('warning', 'description', 'Product has no description.'))
            category_value = _text(row.get('category'))
            category = categories_by_name.get(category_value.casefold()) or categories_by_slug.get(slugify(category_value).casefold())
            if category:
                group['product']['category_id'] = str(category.id)
                group['product']['category_name'] = category.name
            elif category_value:
                # Unknown (or inactive) categories are resolved during
                # processing — created if missing — instead of failing
                # validation, so a typo'd/new collection never blocks import.
                group['product'].pop('category_id', None)
                group['product']['category_name'] = category_value
                if not any(item.get('field') == 'category' for item in group['warnings']):
                    group['warnings'].append(_issue(
                        'warning', 'category',
                        f'Category "{category_value}" will be created during import if it does not exist.'))
            status_value = _text(row.get('status')).upper()
            if status_value:
                if status_value in ('PUBLISHED', 'ACTIVE'):
                    status_value = Product.Status.ACTIVE
                elif status_value == 'DRAFT':
                    status_value = Product.Status.DRAFT
                elif status_value == 'ARCHIVED':
                    status_value = Product.Status.ARCHIVED
                else:
                    errors.append(_issue('error', 'status', 'status must be DRAFT, ACTIVE, or ARCHIVED.', row_number))
                if group['product'].get('status') and group['product']['status'] != status_value:
                    message = 'Conflicting status values for product_code.'
                    errors.append(_issue('error', 'status', message, row_number))
                    group['errors'].append(_issue('error', 'status', message))
                else:
                    group['product']['status'] = status_value
                if status_value and status_value != job.import_status:
                    warnings.append(_issue('warning', 'status', f'Import status {job.get_import_status_display()} will be applied.', row_number))
            row['_price_minor'] = None
            try:
                row['_price_minor'] = _money_to_minor(row.get('price'))
            except ValueError as exc:
                errors.append(_issue('error', 'price', str(exc), row_number))
            row['_stock'] = None
            try:
                row['_stock'] = _stock_value(row.get('stock'))
                if row['_stock'] == 0:
                    warnings.append(_issue('warning', 'stock', 'Stock is zero.', row_number))
            except ValueError as exc:
                errors.append(_issue('error', 'stock', str(exc), row_number))
            color_hex = _text(row.get('color_hex'))
            row['_color_hex'] = ''
            if color_hex:
                try:
                    row['_color_hex'] = normalize_hex(color_hex)
                except ValidationError as exc:
                    errors.append(_issue('error', 'color_hex', exc.messages[0], row_number))
            combination = (
                code.casefold(),
                _text(row.get('size')).casefold(),
                _text(row.get('color')).casefold(),
            )
            if all(combination):
                seen_combinations[combination].append(row_number)
            row['_row_status'] = 'valid'

        candidate_codes = {group['product_code'] for group in groups.values()}
        if candidate_codes:
            existing_products = {
                product.product_code.casefold(): product
                for product in Product.objects.filter(
                    product_code__in=set(candidate_codes) | {code.lower() for code in candidate_codes},
                ).only('id', 'product_code')
            }
        candidate_skus = {row['_sku'] for row in rows if row.get('_sku')}
        if candidate_skus:
            existing_variants = {
                variant.sku.casefold(): variant
                for variant in ProductVariant.objects.filter(
                    sku__in=set(candidate_skus) | {sku.lower() for sku in candidate_skus},
                ).only('id', 'product_id', 'sku', 'size', 'color', 'stock_quantity')
            }

        for sku, row_numbers in seen_skus.items():
            if len(row_numbers) > 1:
                for row_number in row_numbers:
                    errors.append(_issue('error', 'sku', f'Duplicate SKU in package: {sku.upper()}.', row_number))
        for combination, row_numbers in seen_combinations.items():
            if len(row_numbers) > 1:
                for row_number in row_numbers:
                    errors.append(_issue('error', 'variant', 'Duplicate size and color combination in package.', row_number))

        for code, group in groups.items():
            product = group['product']
            product_code = product.get('product_code', code)
            existing = existing_products.get(code.casefold())
            group['existing_product_id'] = str(existing.pk) if existing else None
            group['action'] = 'update' if existing else 'create'
            image_names = []
            for row in group['rows']:
                row_errors_before = len([item for item in errors if item.get('row_number') == row['_row_number']])
                if row_errors_before:
                    row['_row_status'] = 'error'
                for image_name in row['_image_names']:
                    if image_name not in image_names:
                        image_names.append(image_name)
                if not row.get('_sku'):
                    row['_row_status'] = 'error'
                existing_variant = existing_variants.get(row.get('_sku', '').casefold())
                if existing_variant:
                    if not existing or str(existing_variant.product_id) != str(existing.pk):
                        message = f'SKU {row["_sku"]} belongs to a different product.'
                        errors.append(_issue('error', 'sku', message, row['_row_number']))
                        group['errors'].append(_issue('error', 'sku', message))
                    row['_existing_variant_id'] = str(existing_variant.pk)
                else:
                    row['_existing_variant_id'] = None
                combination = (
                    code.casefold(),
                    _text(row.get('size')).casefold(),
                    _text(row.get('color')).casefold(),
                )
                other_variant = next((
                    candidate for candidate in existing_variants.values()
                    if candidate.product_id == (existing.pk if existing else None)
                    and (candidate.size or '').casefold() == combination[1]
                    and (candidate.color or '').casefold() == combination[2]
                    and str(candidate.pk) != row.get('_existing_variant_id')
                ), None)
                if other_variant and row.get('_existing_variant_id') is None:
                    message = 'A variant with this size and color already exists for the product.'
                    errors.append(_issue('error', 'variant', message, row['_row_number']))
                    group['errors'].append(_issue('error', 'variant', message))
            group['image_names'] = image_names
            if not image_names:
                group['warnings'].append(_issue('warning', 'images', 'Product has no images.'))
            elif len(image_names) == 1:
                group['warnings'].append(_issue('warning', 'images', 'Product has only one image.'))
            for warning in group['warnings']:
                warnings.append(warning)
            group['status'] = 'error' if group['errors'] else 'ready'
            if group['status'] == 'ready':
                for row in group['rows']:
                    row_status = any(item.get('row_number') == row['_row_number'] and item['level'] == 'error' for item in errors)
                    row['_row_status'] = 'error' if row_status else 'valid'
                if any(row['_row_status'] == 'error' for row in group['rows']):
                    group['status'] = 'error'

        product_previews = []
        serializable_groups = []
        for group in groups.values():
            serializable_groups.append({
                'product_code': group['product_code'],
                'product': group['product'],
                'rows': group['rows'],
                'image_names': group['image_names'],
                'status': group['status'],
                'action': group['action'],
                'errors': group['errors'],
                'warnings': group['warnings'],
            })
        total_images = set()
        for group in groups.values():
            total_images.update(group['image_names'])
            product_previews.append({
                'product_code': group['product_code'],
                'name': group['product'].get('name', ''),
                'category': group['product'].get('category_name', ''),
                'row_numbers': [row['_row_number'] for row in group['rows']],
                'variant_count': len(group['rows']),
                'image_count': len(group['image_names']),
                'image_names': group['image_names'],
                'action': group['action'],
                'status': group['status'],
                'errors': group['errors'],
                'warnings': group['warnings'],
            })
        return cls._finish(job, rows, errors, warnings, len(groups), len(rows), len(total_images), product_previews, serializable_groups)

    @staticmethod
    def _find_image_member(package, filename):
        if '/' in filename or '\\' in filename or filename in ('', '.', '..'):
            return None
        matches = [
            name for name in package.image_members
            if PurePosixPath(name).name == filename
        ]
        if len(matches) == 1:
            return matches[0]
        case_matches = [
            name for name in matches
            if PurePosixPath(name).name.casefold() == filename.casefold()
        ]
        return case_matches[0] if len(case_matches) == 1 else None

    @classmethod
    def _finish(cls, job, rows, errors, warnings, product_count, row_count, image_count, product_previews=None, groups=None):
        job.total_rows = row_count
        job.processed_rows = 0
        job.error_count = len(errors)
        job.warning_count = len(warnings)
        job.validation_completed_at = timezone.now()
        job.status = ImportJob.Status.READY
        if errors and not rows:
            job.status = ImportJob.Status.FAILED
        preview_products = product_previews or []
        row_results = []
        for row in rows:
            row_number = row.get('_row_number')
            row_errors = [item for item in errors if item.get('row_number') == row_number]
            row_warnings = [item for item in warnings if item.get('row_number') == row_number]
            row_results.append({
                'row_number': row_number,
                'product_code': row.get('_product_code', ''),
                'sku': row.get('_sku', ''),
                'status': 'error' if row_errors else 'ready',
                'errors': row_errors,
                'warnings': row_warnings,
            })
        result = {
            'summary': {
                'products': product_count,
                'variants': row_count,
                'images': image_count,
                'errors': len(errors),
                'warnings': len(warnings),
            },
            'products': preview_products,
            'groups': groups or [],
            'rows': row_results,
            'errors': errors,
            'warnings': warnings,
            'can_confirm': not errors and bool(rows),
        }
        job.validation_results = result
        job.error_details = {'errors': errors, 'warnings': warnings}
        job.save(update_fields=[
            'status', 'total_rows', 'processed_rows', 'error_count',
            'warning_count', 'validation_completed_at', 'validation_results',
            'error_details', 'updated_at',
        ])
        return result


class BulkImportExecutionService:
    @classmethod
    def confirm(cls, job, actor=None):
        job = ImportJob.objects.get(pk=job.pk)
        if job.status != ImportJob.Status.READY:
            raise BulkImportConflict('This import is not ready to confirm.')
        if job.error_count or not job.validation_results.get('can_confirm'):
            raise BulkImportConflict('Resolve all import errors before confirming.')
        job.status = ImportJob.Status.PROCESSING
        job.started_at = timezone.now()
        job.processing_token = None
        job.processing_lease_until = None
        job.import_results = {
            'products': [],
            'variants': [],
            'images': [],
            'errors': [],
            'warnings': job.validation_results.get('warnings', []),
            'next_index': 0,
        }
        job.save(update_fields=[
            'status', 'started_at', 'processing_token', 'processing_lease_until',
            'import_results', 'updated_at',
        ])
        AuditLogService.log(
            'bulk_import_confirmed', actor=actor or job.uploaded_by,
            category='catalog', object_type='import_job', object_id=job.pk,
            object_repr=job.filename, description='Bulk import confirmed.',
            metadata={'filename': job.filename, 'import_status': job.import_status},
        )
        return job

    @classmethod
    def process_chunk(cls, job_id, limit=10, actor=None):
        """Import one chunk of product groups.

        Public behaviour is unchanged: claim the lease, import up to ``limit``
        groups, then either finish the job or release the lease for the next
        caller. The body lives in :meth:`_execute_chunk` so the Celery worker
        in ``catalog.tasks`` drives exactly the same code.
        """
        limit = min(max(int(limit or 10), 1), 25)
        token = cls._claim(job_id)
        if token is None:
            job = ImportJob.objects.get(pk=job_id)
            return job, False
        return cls._execute_chunk(job_id, token, limit, actor)

    @classmethod
    def _execute_chunk(cls, job_id, token, limit, actor=None):
        job = ImportJob.objects.get(pk=job_id)
        result = job.import_results or {}
        previews = job.validation_results.get('products', [])
        completed_codes = {item.get('product_code') for item in result.get('products', [])}
        failed_codes = {item.get('product_code') for item in result.get('errors', [])}
        next_index = int(result.get('next_index', 0))
        if next_index >= len(previews):
            cls._finish_job(job, token, actor)
            return ImportJob.objects.get(pk=job_id), True
        package = None
        stopped = False
        try:
            package = BulkImportPackage(job)
            package.__enter__()
            for preview in previews[next_index:next_index + limit]:
                if not cls._still_owns(job_id, token):
                    # The import was cancelled (or the lease was taken over by
                    # a newer execution). Stop at a product-group boundary: the
                    # group already inside its atomic block still commits, but
                    # no further group is started and no counter is written.
                    stopped = True
                    break
                if preview.get('product_code') in completed_codes or preview.get('product_code') in failed_codes:
                    next_index += 1
                    result['next_index'] = next_index
                    job.import_results = result
                    job.save(update_fields=['import_results', 'updated_at'])
                    continue
                group = cls._find_group(job, preview)
                product_result = {'product_code': preview['product_code'], 'action': preview['action']}
                created_keys = []
                try:
                    with transaction.atomic():
                        product_result, variant_results, image_results, uploaded = cls._import_group(
                            job, group, package, actor or job.uploaded_by, created_keys)
                    result.setdefault('products', []).append(product_result)
                    result.setdefault('variants', []).extend(variant_results)
                    result.setdefault('images', []).extend(image_results)
                    job.processed_rows += len(group['rows'])

                    job.successful_rows += len(group['rows'])
                    job.created_products += int(product_result.get('action') == 'create')
                    job.updated_products += int(product_result.get('action') == 'update')
                    job.created_variants += sum(1 for item in variant_results if item['action'] == 'create')
                    job.updated_variants += sum(1 for item in variant_results if item['action'] == 'update')
                    job.uploaded_images += uploaded
                except Exception as exc:
                    for key in created_keys:
                        try:
                            default_storage.delete(key)
                        except Exception:
                            logger.exception('Could not clean up imported image %s', key)
                    logger.exception('Bulk import product %s failed', preview.get('product_code'))
                    result.setdefault('errors', []).append({
                        'product_code': preview.get('product_code'),
                        'message': 'The product could not be imported. No changes were saved for it.',
                    })
                    job.error_count += 1
                    job.failed_rows += len(group['rows'])
                    job.processed_rows += len(group['rows'])
                    job.error_details = {
                        **(job.error_details or {}),
                        'import_errors': result.get('errors', []),
                    }
                next_index += 1
                result['next_index'] = next_index
                job.import_results = result
                job.save(update_fields=[
                    'processed_rows', 'successful_rows', 'failed_rows', 'error_count',
                    'created_products', 'updated_products', 'created_variants',
                    'updated_variants', 'uploaded_images', 'import_results', 'error_details', 'updated_at',
                ])
            if stopped:
                cls._release(job, token)
                return ImportJob.objects.get(pk=job_id), False
            if next_index >= len(previews):
                cls._finish_job(job, token, actor)
                return ImportJob.objects.get(pk=job_id), True
            job.processing_token = None
            job.processing_lease_until = None
            job.save(update_fields=['processing_token', 'processing_lease_until', 'updated_at'])
            return job, False
        except Exception:
            cls._release(job, token)
            raise
        finally:
            if package is not None:
                package.close()

    @classmethod
    def _claim(cls, job_id):
        now = timezone.now()
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().filter(pk=job_id).first()
            if not job or job.status != ImportJob.Status.PROCESSING:
                return None
            if job.processing_lease_until and job.processing_lease_until > now:
                return None
            token = uuid4()
            job.processing_token = token
            job.processing_lease_until = now + timedelta(minutes=10)
            job.save(update_fields=['processing_token', 'processing_lease_until', 'updated_at'])
            return token

    @classmethod
    def _release(cls, job, token):
        try:
            ImportJob.objects.filter(pk=job.pk, processing_token=token).update(
                processing_token=None, processing_lease_until=None, updated_at=timezone.now())
        except Exception:
            logger.exception('Could not release bulk import lease for job %s', job.pk)

    @classmethod
    def _still_owns(cls, job_id, token):
        """True while this execution still holds the processing lease *and* the
        job is still PROCESSING — i.e. it has not been cancelled underneath us
        and no newer execution has taken the lease over."""
        return ImportJob.objects.filter(
            pk=job_id,
            processing_token=token,
            status=ImportJob.Status.PROCESSING,
        ).exists()

    @classmethod
    def _finish_job(cls, job, token, actor=None):
        now = timezone.now()
        failed = job.failed_rows > 0
        status = ImportJob.Status.COMPLETED_WITH_ERRORS if failed else ImportJob.Status.COMPLETED
        ImportJob.objects.filter(pk=job.pk, processing_token=token).update(
            status=status, completed_at=now, processing_token=None,
            processing_lease_until=None, updated_at=now)
        job.status = status
        job.completed_at = now
        job.processing_token = None
        job.processing_lease_until = None
        AuditLogService.log(
            'bulk_import_completed' if not failed else 'bulk_import_failed',
            actor=actor or job.uploaded_by, category='catalog', object_type='import_job',
            object_id=job.pk, object_repr=job.filename,
            description='Bulk import completed.' if not failed else 'Bulk import completed with errors.',
            metadata={
                'filename': job.filename,
                'created_products': job.created_products,
                'updated_products': job.updated_products,
                'created_variants': job.created_variants,
                'updated_variants': job.updated_variants,
                'uploaded_images': job.uploaded_images,
                'error_count': job.error_count,
                'warning_count': job.warning_count,
                'failed_rows': job.failed_rows,
            }, result='failure' if failed else 'success')
        try:
            notify_staff(
                'system',
                'Bulk import completed' if not failed else 'Bulk import completed with errors',
                f'{job.filename}: {job.created_products} products created, {job.updated_products} updated, {job.failed_rows} rows failed.',
                link=f'/admin/dashboard/products/import/{job.pk}/report/',
                event_key=f'bulk-import:{job.pk}',
                recipient=actor or job.uploaded_by,
                event_type='bulk_import_completed' if not failed else 'bulk_import_failed',
                severity='info' if not failed else 'medium',
                resource_type='import_job',
                resource_id=str(job.pk),
                metadata={'error_count': job.error_count, 'warning_count': job.warning_count},
            )
        except Exception:
            logger.exception('Bulk import completion notification failed for job %s', job.pk)
        queue_import_outcome_email(
            'bulk_import_failed' if failed else 'bulk_import_completed',
            job,
            ('Bulk import completed with errors.' if failed
             else 'Bulk import completed.'),
        )
        _delete_temporary_import(job.pk)
        ImportJob.objects.filter(pk=job.pk).update(package_path='')
        job.package_path = ''
        return ImportJob.objects.get(pk=job.pk)

    @classmethod
    def _find_group(cls, job, preview):
        groups = job.validation_results.get('groups', [])
        for group in groups:
            if group.get('product_code') == preview.get('product_code'):
                return group
        raise BulkImportConflict('Validated product data is no longer available.')

    @classmethod
    def _resolve_category(cls, product_data):
        """Return the category for validated product data, creating it when missing."""
        category_id = product_data.get('category_id')
        if category_id:
            category = Category.objects.filter(pk=category_id).first()
            if category is not None:
                return category
        name = (_text(product_data.get('category_name')) or _text(product_data.get('category')) or '')[:120].strip()
        if not name:
            raise BulkImportConflict('Category is required.')
        slug = slugify(name)[:100]
        category = None
        if slug:
            category = Category.objects.filter(slug=slug).first()
        if category is None:
            category = Category.objects.filter(name__iexact=name).first()
        if category is not None:
            return category
        try:
            with transaction.atomic():
                return Category.objects.create(
                    name=name,
                    slug=slug or f'category-{uuid4().hex[:10]}',
                    description='Created automatically from bulk product import.',
                    is_active=True,
                )
        except IntegrityError:
            category = None
            if slug:
                category = Category.objects.filter(slug=slug).first()
            if category is None:
                category = Category.objects.filter(name__iexact=name).first()
            if category is None:
                raise BulkImportConflict(f'Category "{name}" could not be created.')
            return category

    @classmethod
    def _import_group(cls, job, group, package, actor, created_keys):
        product_data = group['product']
        rows = group['rows']
        category = cls._resolve_category(product_data)
        code = group['product_code']
        product = Product.objects.select_for_update().filter(product_code=code).first()
        if product is None:
            product = Product(
                category=category,
                name=product_data['name'],
                slug=_product_slug(product_data['name'], code),
                product_code=code,
                description=product_data.get('description', ''),
                tagline=product_data.get('tagline', ''),
                price_minor=min(row['_price_minor'] for row in rows if row.get('_price_minor') is not None),
                status=job.import_status,
                is_active=job.import_status == Product.Status.ACTIVE,
            )
            product.save()
            product_action = 'create'
        else:
            product.category = category
            product.name = product_data['name']
            product.description = product_data.get('description') or product.description
            product.tagline = product_data.get('tagline') or product.tagline
            product.status = job.import_status
            product.is_active = job.import_status == Product.Status.ACTIVE
            product.save(update_fields=['category', 'name', 'description', 'tagline', 'status', 'is_active', 'updated_at'])
            product_action = 'update'
        variant_results = []
        variant_by_row = {}
        for row in rows:
            sku = row['_sku']
            variant = ProductVariant.objects.select_for_update().filter(sku=sku).first()
            if variant and variant.product_id != product.pk:
                raise BulkImportConflict(f'SKU {sku} belongs to a different product.')
            collision = ProductVariant.objects.select_for_update().filter(
                product=product, size=row.get('size', ''), color=row.get('color', ''))
            if variant:
                collision = collision.exclude(pk=variant.pk)
            if collision.exists():
                raise BulkImportConflict('A duplicate size and color variant exists.')
            values = {
                'product': product,
                'sku': sku,
                'size': _text(row.get('size'))[:40],
                'color': _text(row.get('color'))[:80],
                'color_hex': row.get('_color_hex', ''),
                'price_minor': row['_price_minor'],
                'stock_quantity': row['_stock'],
                'is_active': True,
            }
            if variant is None:
                variant = ProductVariant.objects.create(**values)
                InventoryTransaction.objects.create(
                    variant=variant, quantity_delta=row['_stock'], previous_quantity=0,
                    new_quantity=row['_stock'], reason='bulk_import', actor=actor)
                action = 'create'
            else:
                previous_stock = variant.stock_quantity
                for field, value in values.items():
                    if field not in ('product', 'stock_quantity'):
                        setattr(variant, field, value)
                variant.save(update_fields=['sku', 'size', 'color', 'color_hex', 'price_minor', 'is_active'])
                if previous_stock != row['_stock']:
                    from inventory.services import adjust_stock
                    adjust_stock(variant.pk, row['_stock'] - previous_stock, 'bulk_import', actor)
                action = 'update'
            variant_by_row[row['_row_number']] = variant
            variant_results.append({
                'sku': sku, 'row_number': row['_row_number'], 'action': action,
                'product_id': str(product.pk),
            })
        image_results = []
        product_urls = Product.normalize_images(product.images)
        uploaded = 0
        seen_image_names = set()
        for image_name in group.get('image_names', []):
            image_member = BulkImportValidationService._find_image_member(package, image_name)
            if not image_member:
                raise BulkImportConflict(f'Image {image_name} is no longer present in the package.')
            image_data = package.read(image_member, int(setting('BULK_IMPORT_MAX_IMAGE_BYTES', 10 * 1024 * 1024)))
            metadata = _image_metadata(image_data, image_member)
            safe_name = PurePosixPath(image_member).name
            key = f'products/{slugify(code)}/{safe_name}'
            if not default_storage.exists(key):
                content = ContentFile(image_data, name=safe_name)
                content.content_type = metadata['mime_type']
                saved_key = default_storage.save(key, content)
                created_keys.append(saved_key)
                uploaded += 1
            else:
                saved_key = key
            image_url = default_storage.url(saved_key)
            if image_url not in product_urls:
                product_urls.append(image_url)
            for row in group['rows']:
                if image_name not in row.get('_image_names', []):
                    continue
                variant = variant_by_row.get(row['_row_number'])
                ProductImage.objects.get_or_create(
                    product=product, variant=variant, image_url=image_url,
                    defaults={'order': len(image_results) + 1, 'is_primary': not product_urls[:-1]},
                )
                image_results.append({
                    'filename': image_name, 'url': image_url,
                    'variant_id': str(variant.pk) if variant else None,
                })
            seen_image_names.add(image_name)
        product.images = product_urls
        all_variants = list(ProductVariant.objects.filter(product=product))
        variant_prices = [variant.price_minor for variant in all_variants if variant.price_minor is not None]
        if variant_prices:
            product.price_minor = min(variant_prices)
        product.stock_quantity = sum(variant.stock_quantity for variant in all_variants)
        product.save(update_fields=['images', 'price_minor', 'stock_quantity', 'updated_at'])
        product_images = list(ProductImage.objects.filter(product=product).order_by('order', 'id'))
        for index, image in enumerate(product_images):
            image.is_primary = index == 0
            image.save(update_fields=['is_primary'])
        return (
            {'product_code': code, 'product_id': str(product.pk), 'action': product_action,
             'variant_count': len(variant_results), 'image_count': len(seen_image_names)},
            variant_results,
            image_results,
            uploaded,
        )

    @classmethod
    def cancel(cls, job, actor=None):
        """Cancel an import, including one that is mid-flight.

        A PROCESSING job is stopped cooperatively: the status flips to CANCELLED
        immediately (so the admin sees it and no new chunk can be claimed) and
        the running execution — browser-driven or Celery — notices at the next
        product-group boundary and releases its lease. The in-flight group still
        commits its own atomic transaction, which is why the worker never
        rewrites the job once it has been cancelled.
        """
        job.status = ImportJob.Status.CANCELLED
        job.cancelled_at = timezone.now()
        job.completed_at = job.cancelled_at
        job.processing_token = None
        job.processing_lease_until = None
        job.save(update_fields=[
            'status', 'cancelled_at', 'completed_at',
            'processing_token', 'processing_lease_until', 'updated_at',
        ])
        if job.package_path:
            if Path(job.package_path).is_absolute():
                _delete_temporary_import(job.pk)
            else:
                try:
                    default_storage.delete(job.package_path)
                except Exception:
                    logger.exception('Could not remove cancelled import package %s', job.pk)
        AuditLogService.log(
            'bulk_import_cancelled', actor=actor or job.uploaded_by,
            category='catalog', object_type='import_job', object_id=job.pk,
            object_repr=job.filename, description='Bulk import cancelled.',
            metadata={'filename': job.filename}, result='failure')
        return job


class BulkProductImportService:
    max_upload_bytes = 500 * 1024 * 1024

    @classmethod
    def create_job(cls, uploaded_file, actor, import_status=Product.Status.DRAFT):
        filename = _text(getattr(uploaded_file, 'name', '')) or 'import.zip'
        filename = PurePosixPath(filename.replace('\\', '/')).name
        if not filename.lower().endswith('.zip'):
            raise BulkImportPackageError('Only ZIP packages are accepted.')
        max_upload = int(setting('BULK_IMPORT_MAX_ZIP_BYTES', cls.max_upload_bytes))
        file_size = getattr(uploaded_file, 'size', None)
        if file_size is None:
            uploaded_file.seek(0, 2)
            file_size = uploaded_file.tell()
            uploaded_file.seek(0)
        if file_size > max_upload:
            raise BulkImportPackageError('ZIP file exceeds the maximum upload size.')
        digest = hashlib.sha256()
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
        uploaded_file.seek(0)
        if str(import_status).upper() == 'PUBLISHED':
            import_status = Product.Status.ACTIVE
        if import_status not in (Product.Status.DRAFT, Product.Status.ACTIVE):
            raise BulkImportPackageError('Choose Draft or Published for the import status.')
        job = ImportJob.objects.create(
            uploaded_by=actor, filename=filename, package_size=file_size,
            package_sha256=digest.hexdigest(), import_status=import_status,
        )
        package_path = _temporary_package_path(job.pk)
        try:
            package_path.parent.mkdir(parents=True, exist_ok=True)
            uploaded_file.seek(0)
            with package_path.open('wb') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            job.package_path = str(package_path)
            job.save(update_fields=['package_path', 'updated_at'])
        except Exception:
            _delete_temporary_import(job.pk)
            job.status = ImportJob.Status.FAILED
            job.error_details = {'errors': [{'level': 'error', 'field': 'archive', 'message': 'The package could not be stored.'}]}
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_details', 'completed_at', 'updated_at'])
            AuditLogService.log(
                'bulk_import_failed', actor=actor, category='catalog',
                object_type='import_job', object_id=job.pk, object_repr=filename,
                description='Bulk import package could not be stored.',
                metadata={'filename': filename}, result='failure')
            raise
        AuditLogService.log(
            'bulk_import_started', actor=actor, category='catalog', object_type='import_job',
            object_id=job.pk, object_repr=filename, description='Bulk import package uploaded.',
            metadata={'filename': filename, 'package_size': file_size})
        return job

    @classmethod
    def validate(cls, job, actor=None):
        if job.status == ImportJob.Status.CANCELLED:
            raise BulkImportConflict('Cancelled imports cannot be validated.')
        if job.status not in (ImportJob.Status.UPLOADED, ImportJob.Status.FAILED, ImportJob.Status.READY):
            raise BulkImportConflict('This import cannot be validated in its current state.')
        job.status = ImportJob.Status.VALIDATING
        job.save(update_fields=['status', 'updated_at'])
        result = BulkImportValidationService.validate(job)
        AuditLogService.log(
            'bulk_import_validated', actor=actor or job.uploaded_by,
            category='catalog', object_type='import_job', object_id=job.pk,
            object_repr=job.filename, description='Bulk import package validated.',
            metadata={'filename': job.filename, 'summary': result.get('summary', {})},
            result='success' if not result.get('errors') else 'failure')
        return job

    @classmethod
    def confirm(cls, job, actor=None):
        return BulkImportExecutionService.confirm(job, actor=actor)

    @classmethod
    def process_chunk(cls, job, limit=10, actor=None):
        return BulkImportExecutionService.process_chunk(job.pk, limit=limit, actor=actor)

    @classmethod
    def cancel(cls, job, actor=None):
        return BulkImportExecutionService.cancel(job, actor=actor)


def job_data(job):
    result = job.import_results or {}
    return {
        'id': str(job.pk),
        'filename': job.filename,
        'status': job.status,
        'import_status': job.import_status,
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'cancelled_at': job.cancelled_at.isoformat() if job.cancelled_at else None,
        'processed_rows': job.processed_rows,
        'total_rows': job.total_rows,
        'successful_rows': job.successful_rows,
        'failed_rows': job.failed_rows,
        'created_products': job.created_products,
        'updated_products': job.updated_products,
        'created_variants': job.created_variants,
        'updated_variants': job.updated_variants,
        'uploaded_images': job.uploaded_images,
        'error_count': job.error_count,
        'warning_count': job.warning_count,
        'validation_results': job.validation_results,
        'import_results': result,
        'progress': round((job.processed_rows / job.total_rows) * 100, 2) if job.total_rows else 0,
    }
