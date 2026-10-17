import logging
import hashlib
import math
import os
import secrets
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.utils.text import get_valid_filename

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access_control.drf_permissions import AdminPermission
from admin_ui.models import AdminNotification
from audit.services import AuditLogService
from catalog.bulk_import import BulkImportError, BulkProductImportService, job_data
from catalog.models import BulkUploadSession, Category, ImportJob, Product, ProductVariant
from catalog.serializers import CategorySerializer, ProductSerializer
from catalog.services import BulkImportTemplateService
from catalog.tasks import enqueue_import_job
from emails.services import sweep_pending_emails
from inventory.services import adjust_stock, expire_reservations
from replica.services.sync import (
    ReplicaAlreadyRunning,
    ReplicaNotConfigured,
    sync_replica,
)

from .serializers import CategoryWriteSerializer, ProductWriteSerializer, StockAdjustmentSerializer
from .services import create_product, update_product

logger = logging.getLogger('admin_api.views')


def _notification_data(notification):
    return {
        'id': str(notification.pk),
        'category': notification.category,
        'severity': notification.severity,
        'title': notification.title,
        'message': notification.message,
        'link': notification.link,
        'eventType': notification.event_type,
        'resourceType': notification.resource_type,
        'resourceId': notification.resource_id,
        'requestId': notification.request_id,
        'createdAt': notification.created_at.isoformat(),
        'read': notification.is_read,
        'presented': notification.presented_at is not None,
    }


class AdminAPIView(APIView):
    """Base view for admin endpoints.

    Uses MODEZA granular permissions (roles/direct permissions) instead of the
    coarse Supabase role check, and accepts Django-session staff too. Subclasses
    declare ``required_permissions`` for the exact codes they need.
    """

    permission_classes = [AdminPermission]
    throttle_scope = 'admin'
    required_permissions = None


class AdminProductCreateView(AdminAPIView):
    required_permissions = ['products.create']

    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = create_product(serializer.validated_data)
        AuditLogService.log(
            'create',
            object_type='product',
            object_id=product.pk,
            object_repr=product.name,
            category='catalog',
            status_code=201,
            description=f'Product created: {product.name}.',
        )
        return Response(ProductSerializer(product).data, status=201)


class AdminProductUpdateView(AdminAPIView):
    required_permissions = ['products.update']

    def patch(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        before = product_to_input(product)
        serializer = ProductWriteSerializer(
            before, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = update_product(product, serializer.validated_data)
        AuditLogService.log(
            'update',
            object_type='product',
            object_id=updated.pk,
            object_repr=updated.name,
            category='catalog',
            metadata={'changed': _field_diff(before, product_to_input(updated))},
            description=f'Product updated: {updated.name}.',
        )
        return Response(ProductSerializer(updated).data)


class AdminProductArchiveView(AdminAPIView):
    required_permissions = ['products.update']

    def post(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id)
        previous = product.status
        product.status = Product.Status.ARCHIVED
        product.save(update_fields=['status', 'updated_at'])
        AuditLogService.log(
            'update',
            object_type='product',
            object_id=product.pk,
            object_repr=product.name,
            category='catalog',
            metadata={'status_changed': {'from': previous,
                                         'to': product.status}},
            description=f'Product archived: {product.name}.',
        )
        return Response(ProductSerializer(product).data)


class AdminCategoryCreateView(AdminAPIView):
    required_permissions = ['categories.create']

    def post(self, request):
        serializer = CategoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = Category.objects.create(
            name=data['name'], slug=data['slug'], description=data.get(
                'description', ''),
            is_active=data.get('isActive', True))
        AuditLogService.log(
            'create',
            object_type='category',
            object_id=category.pk,
            object_repr=category.name,
            category='catalog',
            status_code=201,
            description=f'Category created: {category.name}.',
        )
        return Response(CategorySerializer(category).data, status=201)


class AdminStockAdjustmentView(AdminAPIView):
    required_permissions = ['inventory.adjust']

    def patch(self, request, variant_id):
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        adjust_stock(
            variant.id, serializer.validated_data['delta'], serializer.validated_data['reason'], request.user)
        variant.refresh_from_db()
        return Response({'variantId': str(variant.id), 'stockQuantity': variant.stock_quantity})


class ExpireReservationsView(AdminAPIView):
    required_permissions = ['inventory.adjust']

    def post(self, request):
        return Response({'expired': expire_reservations()})


class AdminNotificationsView(AdminAPIView):
    def get(self, request):
        notifications = AdminNotification.objects.filter(
            recipient=request.user).order_by('-created_at')[:100]
        unread_count = AdminNotification.objects.filter(
            recipient=request.user, is_read=False).count()
        return Response({
            'unread_count': unread_count,
            'results': [_notification_data(item)
                        for item in notifications],
        })


class AdminUnreadNotificationsView(AdminAPIView):
    def get(self, request):
        unread_count = AdminNotification.objects.filter(
            recipient=request.user, is_read=False).count()
        notifications = AdminNotification.objects.filter(
            recipient=request.user, is_read=False).order_by('-created_at')[:8]
        return Response({
            'unread_count': unread_count,
            'results': [_notification_data(item)
                        for item in notifications],
        })


class AdminNotificationReadView(AdminAPIView):
    def patch(self, request, notification_id):
        notification = get_object_or_404(
            AdminNotification, pk=notification_id, recipient=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
        return Response({'ok': True})


class AdminNotificationsPresentView(AdminAPIView):
    """Atomically claim popup presentation for a set of notification IDs."""

    def post(self, request):
        ids = request.data.get('ids') or []
        if not isinstance(ids, list):
            return Response({'ok': False, 'error': 'ids must be a list'},
                            status=400)
        cleaned = [str(raw) for raw in ids[:100] if isinstance(raw, str)]
        if not cleaned:
            return Response({'ok': True, 'presented': []})

        from django.db import transaction

        with transaction.atomic():
            rows = AdminNotification.objects.select_for_update().filter(
                recipient=request.user,
                pk__in=cleaned,
            )
            won = []
            for notification in rows:
                if notification.presented_at is None and not notification.is_read:
                    notification.presented_at = timezone.now()
                    notification.save(update_fields=['presented_at'])
                    won.append(notification.pk)
        return Response({
            'ok': True,
            'presented': [str(nid) for nid in won],
        })


class AdminNotificationsReadAllView(AdminAPIView):
    def post(self, request):
        updated = AdminNotification.objects.filter(
            recipient=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now())
        return Response({'ok': True, 'updated': updated})


def _field_diff(before, after):
    """Return {field: {'from': old, 'to': new}} for changed scalar fields."""
    changes = {}
    for key in after:
        if key in ('images', 'details'):
            continue
        if before.get(key) != after.get(key):
            changes[key] = {'from': before.get(key), 'to': after.get(key)}
    return changes


def product_to_input(product):
    return {
        'name': product.name, 'slug': product.slug, 'description': product.description,
        'tagline': product.tagline, 'details': product.details, 'price': product.price_minor / 100,
        'material': product.material, 'careInstructions': product.care_instructions,
        'fitNotes': product.fit_notes, 'modelSize': product.model_size,
        'garmentMeasurements': product.garment_measurements,
        'compareAtPrice': product.compare_at_price_minor / 100 if product.compare_at_price_minor is not None else None,
        'categoryId': product.category_id, 'images': product.images,
        'status': product.status, 'isFeatured': product.is_featured, 'isNewArrival': product.is_new_arrival,
        'isBestSeller': product.is_best_seller,
    }


def _bulk_error(message, code='BULK_IMPORT_ERROR', status=400):
    return Response({'error': {'code': code, 'message': str(message)}}, status=status)


def _import_status(value):
    normalized = str(value or '').strip().upper()
    if normalized in ('PUBLISHED', 'ACTIVE'):
        return Product.Status.ACTIVE
    if normalized in ('', 'DRAFT'):
        return Product.Status.DRAFT
    raise BulkImportError('Choose Draft or Published for the import status.')


# The admin import page posts multipart/form-data (empty FormData bodies for
# validate/confirm/cancel, a limit field for process), while the API default is
# JSON-only — accept all three so browser and JSON clients both work.
BULK_IMPORT_ACTION_PARSERS = [MultiPartParser, FormParser, JSONParser]


class BulkImportUploadView(AdminAPIView):
    required_permissions = ['products.import']
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get('file') or request.FILES.get('package')
        if uploaded_file is None:
            return _bulk_error('Choose a ZIP package to upload.')
        try:
            status = _import_status(request.data.get('status') or request.data.get('import_status'))
            job = BulkProductImportService.create_job(
                uploaded_file, request.user, import_status=status)
        except BulkImportError as exc:
            return _bulk_error(exc)
        except Exception:
            logger.exception('Bulk import upload failed')
            return _bulk_error('The package could not be uploaded. Please try again.', 'BULK_IMPORT_UPLOAD_FAILED', 500)
        return Response(job_data(job), 201)


class BulkUploadSessionView(AdminAPIView):
    """Initialize/status, receive chunks, and finalize resumable ZIP uploads."""
    required_permissions = ['products.import']
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _dir(self, session):
        return Path(settings.MEDIA_ROOT) / '.bulk_uploads' / str(session.pk)

    def _owned(self, request, session_id):
        return get_object_or_404(BulkUploadSession, pk=session_id, owner=request.user, expires_at__gt=timezone.now())

    def get(self, request, session_id):
        session = self._owned(request, session_id)
        have = sorted(int(i) for i in session.received_chunks)
        return Response({'id': str(session.pk), 'chunk_size': session.chunk_size,
                         'received_chunks': have, 'missing_chunks': [i for i in range(session.chunk_count) if i not in have],
                         'chunk_count': session.chunk_count, 'expires_at': session.expires_at.isoformat()})

    def post(self, request, session_id=None):
        if session_id is None:
            try:
                size = int(request.data.get('file_size', 0))
                max_size = int(getattr(settings, 'BULK_IMPORT_MAX_ZIP_BYTES', 500 * 1024 * 1024))
                chunk_size = int(getattr(settings, 'BULK_IMPORT_CHUNK_BYTES', 8 * 1024 * 1024))
                name = get_valid_filename(Path(str(request.data.get('filename', ''))).name)
                status_value = _import_status(request.data.get('import_status'))
                if not name.lower().endswith('.zip') or not 0 < size <= max_size:
                    raise ValueError()
            except (TypeError, ValueError, BulkImportError):
                return _bulk_error('Provide a ZIP filename and a valid file size within the configured limit.')
            session = BulkUploadSession.objects.create(owner=request.user, filename=name, file_size=size,
                chunk_size=chunk_size, chunk_count=math.ceil(size / chunk_size), import_status=status_value,
                expires_at=timezone.now() + timedelta(hours=24))
            self._dir(session).mkdir(parents=True, exist_ok=True)
            return Response({'id': str(session.pk), 'chunk_size': chunk_size, 'chunk_count': session.chunk_count, 'received_chunks': []}, status=201)
        session = self._owned(request, session_id)
        if request.data.get('finalize'):
            have = set(int(i) for i in session.received_chunks)
            if len(have) != session.chunk_count:
                return _bulk_error('Upload is incomplete; resume the missing chunks.')
            path = self._dir(session)
            assembled = path / 'package.zip'
            try:
                with assembled.open('wb') as output:
                    for index in range(session.chunk_count):
                        with (path / str(index)).open('rb') as part:
                            while True:
                                block = part.read(1024 * 1024)
                                if not block: break
                                output.write(block)
                if assembled.stat().st_size != session.file_size:
                    return _bulk_error('Assembled package size does not match the upload.')
                from django.core.files import File
                with assembled.open('rb') as source:
                    job = BulkProductImportService.create_job(File(source, name=session.filename), request.user,
                        import_status=session.import_status)
                session.delete()
                import shutil
                shutil.rmtree(path, ignore_errors=True)
                return Response(job_data(job), status=201)
            except BulkImportError as exc:
                return _bulk_error(exc)
            except Exception:
                logger.exception('Bulk import chunk assembly failed')
                return _bulk_error('The package could not be finalized. Please retry.', 'BULK_IMPORT_FINALIZE_FAILED', 500)
        try:
            index = int(request.data.get('index'))
            part = request.FILES.get('chunk')
            if part is None or index < 0 or index >= session.chunk_count:
                raise ValueError()
            expected = min(session.chunk_size, session.file_size - index * session.chunk_size)
            if part.size != expected:
                return _bulk_error('Chunk size is invalid.')
            raw = part.read()
            digest = hashlib.sha256(raw).hexdigest()
            supplied = request.data.get('sha256')
            if supplied and supplied != digest:
                return _bulk_error('Chunk checksum verification failed.')
            with transaction.atomic():
                locked = BulkUploadSession.objects.select_for_update().get(pk=session.pk, owner=request.user)
                directory = self._dir(locked)
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / str(index)
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                        return _bulk_error('A different chunk already exists at this index.')
                else:
                    temp = directory / (str(index) + '.tmp')
                    with temp.open('wb') as output: output.write(raw)
                    os.replace(temp, target)
                locked.received_chunks = sorted(set(int(i) for i in locked.received_chunks) | {index})
                locked.save(update_fields=['received_chunks'])
            return Response({'received': index, 'sha256': digest})
        except (TypeError, ValueError, BulkUploadSession.DoesNotExist):
            return _bulk_error('Invalid chunk request.')


class BulkImportValidateView(AdminAPIView):
    required_permissions = ['products.import']
    parser_classes = BULK_IMPORT_ACTION_PARSERS

    def post(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)
        try:
            job = BulkProductImportService.validate(job, actor=request.user)
        except BulkImportError as exc:
            return _bulk_error(exc)
        except Exception:
            logger.exception('Bulk import validation failed for job %s', job_id)
            return _bulk_error('The package could not be validated. Please try again.', 'BULK_IMPORT_VALIDATION_FAILED', 500)
        return Response(job_data(job))


class BulkImportPreviewView(AdminAPIView):
    required_permissions = ['products.import']

    def get(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)
        return Response({
            'job': job_data(job),
            'preview': job.validation_results,
        })


class BulkImportConfirmView(AdminAPIView):
    required_permissions = ['products.import']
    parser_classes = BULK_IMPORT_ACTION_PARSERS

    def post(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)
        try:
            requested_status = request.data.get('import_status') or request.data.get('status')
            if requested_status:
                job.import_status = _import_status(requested_status)
                job.save(update_fields=['import_status', 'updated_at'])
            job = BulkProductImportService.confirm(job, actor=request.user)
            if settings.CELERY_WORKER_ENABLED:
                # Background worker owns the job from here; the browser just
                # polls GET .../status. Without a worker the confirm response
                # is unchanged and the page drives /process as it always has.
                enqueue_import_job(job.pk, request.user.pk)
                job.refresh_from_db()
        except BulkImportError as exc:
            return _bulk_error(exc)
        except Exception:
            logger.exception('Bulk import confirmation failed for job %s', job_id)
            return _bulk_error('The import could not be started. Please try again.', 'BULK_IMPORT_CONFIRM_FAILED', 500)
        payload = job_data(job)
        payload['queued'] = settings.CELERY_WORKER_ENABLED
        return Response(payload, 202)


class BulkImportProcessView(AdminAPIView):
    required_permissions = ['products.import']
    parser_classes = BULK_IMPORT_ACTION_PARSERS

    def post(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)
        if settings.CELERY_WORKER_ENABLED:
            # Idempotent kick: the task re-claims the lease itself, so a duplicate
            # message or a stray browser call is harmless.
            try:
                if job.status == ImportJob.Status.PROCESSING:
                    enqueue_import_job(job.pk, request.user.pk)
                    job.refresh_from_db()
            except Exception:
                logger.exception('Bulk import dispatch failed for job %s', job_id)
                return _bulk_error('The import could not continue. Please retry the job.', 'BULK_IMPORT_PROCESS_FAILED', 500)
            payload = job_data(job)
            payload['finished'] = job.status in (
                ImportJob.Status.COMPLETED, ImportJob.Status.COMPLETED_WITH_ERRORS)
            return Response(payload)
        try:
            job, finished = BulkProductImportService.process_chunk(
                job, limit=request.data.get('limit', 10), actor=request.user)
        except BulkImportError as exc:
            return _bulk_error(exc)
        except Exception:
            logger.exception('Bulk import processing failed for job %s', job_id)
            return _bulk_error('The import could not continue. Please retry the job.', 'BULK_IMPORT_PROCESS_FAILED', 500)
        payload = job_data(job)
        payload['finished'] = finished
        return Response(payload)


class BulkImportStatusView(AdminAPIView):
    required_permissions = ['products.import']

    def get(self, request, job_id):
        return Response(job_data(get_object_or_404(ImportJob, pk=job_id)))


class BulkImportCancelView(AdminAPIView):
    required_permissions = ['products.import']
    parser_classes = BULK_IMPORT_ACTION_PARSERS

    def post(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)
        try:
            job = BulkProductImportService.cancel(job, actor=request.user)
        except BulkImportError as exc:
            return _bulk_error(exc)
        return Response(job_data(job))


class BulkImportTemplateView(AdminAPIView):
    required_permissions = ['products.import']

    def get(self, request):
        from django.http import HttpResponse
        xlsx_bytes = BulkImportTemplateService.to_bytes()
        response = HttpResponse(
            xlsx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="modeza_bulk_import_template.xlsx"'
        return response


class BulkImportHistoryView(AdminAPIView):
    required_permissions = ['products.import']

    def get(self, request):
        from django.core.paginator import Paginator
        try:
            page = max(int(request.GET.get('page', 1)), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(max(int(request.GET.get('page_size', 20)), 1), 100)
        except (TypeError, ValueError):
            page_size = 20

        jobs = ImportJob.objects.select_related('uploaded_by').all()

        paginator = Paginator(jobs, page_size)
        page_obj = paginator.get_page(page)

        results = []
        for job in page_obj:
            results.append({
                'id': str(job.id),
                'filename': job.filename,
                'status': job.status,
                'uploaded_by': job.uploaded_by.email if job.uploaded_by else 'Unknown',
                'created_at': job.created_at.isoformat(),
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                'products_created': job.created_products,
                'products_updated': job.updated_products,
                'variants_created': job.created_variants,
                'variants_updated': job.updated_variants,
                'images_uploaded': job.uploaded_images,
                'error_count': job.error_count,
                'warning_count': job.warning_count,
            })

        return Response({
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'current_page': page_obj.number,
            'results': results,
        })


class BulkImportReportView(AdminAPIView):
    required_permissions = ['products.import']

    def get(self, request, job_id):
        job = get_object_or_404(ImportJob, pk=job_id)

        return Response({
            'id': str(job.id),
            'filename': job.filename,
            'status': job.status,
            'uploaded_by': job.uploaded_by.email if job.uploaded_by else 'Unknown',
            'import_status': job.import_status,
            'created_at': job.created_at.isoformat(),
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'summary': {
                'products_created': job.created_products,
                'products_updated': job.updated_products,
                'variants_created': job.created_variants,
                'variants_updated': job.updated_variants,
                'images_uploaded': job.uploaded_images,
                'error_count': job.error_count,
                'warning_count': job.warning_count,
            },
            'validation_results': job.validation_results,
            'import_results': job.import_results,
            'error_details': job.error_details,
        })


def _sweep_int(request, name, default):
    raw = request.query_params.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class EmailSweepView(APIView):
    """Deliver every message that is due, for ``EMAIL_DELIVERY_MODE=deferred``.

    In that mode a web request never opens a socket for mail, so *something*
    has to move a row out of ``QUEUED`` — normally an external cron pointing
    at this endpoint once a minute.

    It carries no Django or Supabase authentication because a cron has no
    session. Instead it requires ``EMAIL_SWEEP_TOKEN``, and when that variable
    is unset the endpoint reports itself as unavailable rather than existing
    unauthenticated: an unconfigured deployment must not advertise a POST
    route anyone can knock on.
    """

    authentication_classes = []
    permission_classes = []
    throttle_scope = 'admin'

    def post(self, request):
        configured = (getattr(settings, 'EMAIL_SWEEP_TOKEN', '') or '').strip()
        if not configured:
            return Response(
                {'detail': 'Mail sweeping is not configured.'}, status=404)

        offered = (
            request.headers.get('x-sweep-token')
            or request.query_params.get('token', '')
        )
        if not offered or not secrets.compare_digest(str(offered), configured):
            AuditLogService.log(
                'security_event',
                category='security',
                result='failure',
                severity='critical',
                metadata={'has_token': bool(offered)},
                path=request.path,
                description='Mail sweeper rejected an invalid token.',
            )
            return Response({'detail': 'Invalid sweep token.'}, status=401)

        summary = sweep_pending_emails(
            older_than=max(0, _sweep_int(request, 'olderThan', 45)),
            limit=max(1, _sweep_int(request, 'limit', 10)),
        )
        return Response(summary)


class ReplicaSyncView(APIView):
    """Mirror Django into the Supabase replica schema, for an external cron.

    Deliberately mirrors :class:`EmailSweepView` rather than requiring staff
    credentials: a scheduled job has no session. It therefore carries no
    authentication, and instead requires ``REPLICA_SYNC_TOKEN``. When that
    variable is unset the endpoint reports itself as unavailable instead of
    existing unauthenticated -- an unconfigured deployment must not advertise a
    POST route anyone can knock on.

    Staff-triggered runs go through the admin page instead, which is
    session-authenticated and permission-checked; both call the same
    ``sync_replica`` service function.
    """

    authentication_classes = []
    permission_classes = []
    throttle_scope = 'admin'

    def post(self, request):
        configured = (getattr(settings, 'REPLICA_SYNC_TOKEN', '') or '').strip()
        if not configured:
            return Response(
                {'detail': 'Replica sync is not configured.'}, status=404)

        offered = (
            request.headers.get('x-replica-token')
            or request.query_params.get('token', '')
        )
        if not offered or not secrets.compare_digest(str(offered), configured):
            AuditLogService.log(
                'security_event',
                category='security',
                result='failure',
                severity='critical',
                metadata={'has_token': bool(offered)},
                path=request.path,
                description='Replica sync rejected an invalid token.',
            )
            return Response({'detail': 'Invalid replica token.'}, status=401)

        # A full run writes every table plus the image mirror, so it can take
        # longer than a request should block. `skipStorage` lets a cron keep the
        # relational replica fresh without re-copying unchanged images.
        skip_storage = str(
            request.query_params.get('skipStorage', '')
        ).lower() in {'1', 'true', 'yes', 'on'}

        try:
            summary = sync_replica(triggered_by='cron',
                                   include_storage=not skip_storage)
        except ReplicaNotConfigured as exc:
            return Response({'detail': str(exc)}, status=503)
        except ReplicaAlreadyRunning as exc:
            # Another sync holds the advisory lock. This is expected whenever a
            # manual run overlaps a cron tick, so it is a 409 -- not a failure.
            return Response({'detail': str(exc), 'skipped': True}, status=409)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            logger.exception('Cron-triggered replica sync failed.')
            AuditLogService.log(
                'security_event',
                category='security',
                result='failure',
                severity='high',
                metadata={'error': str(exc)[:500]},
                path=request.path,
                description='Cron replica sync failed.',
            )
            return Response({'detail': f'Replica sync failed: {exc}'},
                            status=500)

        return Response(summary)
