import csv
import io
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.http import HttpResponseNotFound
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.html import format_html
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views import View
from rest_framework.exceptions import ValidationError as DRFValidationError

from audit.constants import AUDIT_ACTIONS
from audit.models import AuditLog
from access_control.services import (
    access_denied_response,
    is_super_admin,
    permission_required,
    super_admin_required,
    user_has_permission,
)
from catalog.bulk_import import BulkImportError, BulkProductImportService, job_data
from catalog.models import Category, ImportJob, Product, ProductVariant
from catalog.services import (
    BulkImportTemplateService,
    ProductGenerationService,
    import_products_from_file,
)
from audit.services import AuditLogService
from assistant.analytics import assistant_analytics
from botique_backend.storage import object_key_from_url, supabase_storage_enabled
from inventory.services import adjust_stock
from orders.models import Order, OrderItem
from orders.services import approve_order, is_order_approvable
from payments.models import PaymentIntent
from receipts.models import Receipt
from receipts.services import read_pdf_bytes, regenerate_receipt
from replica.services.sync import (
    ReplicaAlreadyRunning,
    ReplicaNotConfigured,
    ReplicaStatusUnavailable,
    current_row_counts,
    latest_run,
    pending_request,
    queue_replica_sync,
    replica_configured,
    sync_replica,
)

from .audit_ui import (
    RANGE_CHOICES,
    RESOURCE_TYPE_LABELS,
    SORT_CHOICES,
    SECURITY_ACTIONS,
    SEVERITY_META,
    SEVERITY_ORDER,
    action_label,
    apply_activity_filters,
    build_query,
    category_label,
    compute_summary,
    decorate_audit_logs,
    normalize_filters,
    resolve_date_range,
    severity_meta,
)

from .forms import (
    AdminLoginForm,
    AdminSignupForm,
    CategoryForm,
    ProductCreateForm,
    ProductUpdateForm,
    ProductVariantBulkForm,
    ProductVariantForm,
    StockAdjustmentForm,
)
from .models import AdminNotification, notify_staff


def is_staff(user):
    # ``is_active`` is required so a deactivated staff member is denied
    # immediately — including on already-open sessions.
    return user.is_authenticated and user.is_staff and user.is_active


def is_superuser(user):
    return user.is_authenticated and user.is_superuser and user.is_active


logger = logging.getLogger('admin_ui.views')


def _audit_catalog(action, item, metadata=None, status_code=None):
    AuditLogService.log(
        action,
        object_type=item.__class__.__name__.lower(),
        object_id=item.pk,
        object_repr=str(item),
        category='catalog',
        metadata=metadata,
        status_code=status_code,
        description=f'{action}: {item}',
    )


class AdminLandingPageView(View):
    template_name = 'admin_ui/admin_landing_page.html'

    def get(self, request):
        return render(request, self.template_name, {
            'page_title': 'MODEZA Admin',
            'is_authenticated_staff': bool(
                request.user.is_authenticated and request.user.is_staff),
            'is_superuser': bool(request.user.is_authenticated and request.user.is_superuser),
            'user': request.user if request.user.is_authenticated else None,
        })


class AdminLoginView(LoginView):
    template_name = 'admin_ui/admin_login.html'
    authentication_form = AdminLoginForm
    redirect_authenticated_user = True
    next_page = reverse_lazy('admin-dashboard')


class AdminLogoutView(LogoutView):
    next_page = 'admin-landing'
    http_method_names = ['get', 'post', 'options']

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)


@method_decorator(user_passes_test(is_superuser, login_url='admin-login'), name='dispatch')
class AdminRegisterView(View):
    template_name = 'admin_ui/admin_register.html'

    def get(self, request):
        return self.render_form(
            request, AdminSignupForm(allow_superuser=bool(request.user.is_superuser)))

    def post(self, request):
        form = AdminSignupForm(
            request.POST, allow_superuser=bool(request.user.is_superuser))
        if form.is_valid():
            user = form.save()
            AuditLogService.log(
                'create',
                actor=user,
                category='auth',
                object_type='user',
                object_id=user.pk,
                object_repr=user.get_username(),
                description=f'Administrator account created: {user.get_username()}.',
            )
            notify_staff(
                category='system',
                title='New admin account created',
                message=f'{user.get_full_name() or user.username} ({user.email}) was added as an administrator.',
                recipient=user,
            )
            messages.success(
                request, f'Administrator {user.username} created and granted admin powers.')
            if request.user.is_authenticated:
                return redirect('admin-users')
            return redirect('admin-login')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'Create administrator account',
            'page_subtitle': 'Grant admin powers to a new staff account.',
            'submit_label': 'Create administrator',
        })


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ConfirmActionView(View):
    template_name = 'admin_ui/confirm_page.html'

    @staticmethod
    def _parse_product_ids(raw_value):
        if not raw_value:
            return []

        values = raw_value if isinstance(
            raw_value, (list, tuple)) else [raw_value]
        ids = []
        for item in values:
            for candidate in str(item).split(','):
                value = candidate.strip()
                if not value:
                    continue
                try:
                    ids.append(str(uuid.UUID(value)))
                except ValueError:
                    continue
        return list(dict.fromkeys(ids))

    def _product_title(self, product):
        return product.name if product else 'this product'

    # Granular permission required to confirm/execute each bulk action.
    ACTION_PERMISSIONS = {
        'delete-product': 'products.delete',
        'delete-selected-products': 'products.delete',
        'archive-product': 'products.update',
        'publish-product': 'products.update',
        'publish-selected-products': 'products.update',
        'update-product': 'products.update',
    }

    def _require_action_permission(self, request, action):
        required = self.ACTION_PERMISSIONS.get(action)
        if required and not user_has_permission(request.user, required):
            return access_denied_response(request)
        return None

    def get(self, request):
        action = request.GET.get('action') or 'confirm'
        denied = self._require_action_permission(request, action)
        if denied:
            return denied
        product_id = request.GET.get('product_id')
        product_ids = self._parse_product_ids(request.GET.get('product_ids'))

        if action == 'delete-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            message = f"Are you sure you want to delete product {self._product_title(product)}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'delete-product',
                            'product_id': product_id}
        elif action == 'delete-selected-products' and product_ids:
            products = list(Product.objects.filter(pk__in=product_ids)[:50])
            product_count = len(products)
            message = f"Are you sure you want to delete {product_count} product{'s' if product_count != 1 else ''}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'delete-selected-products',
                            'product_ids': product_ids}
        elif action == 'archive-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            message = f"Are you sure you want to archive product {self._product_title(product)}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'archive-product',
                            'product_id': product_id}
        elif action == 'publish-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            message = f"Are you sure you want to publish product {self._product_title(product)}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'publish-product',
                            'product_id': product_id}
        elif action == 'publish-selected-products' and product_ids:
            products = list(Product.objects.filter(pk__in=product_ids)[:50])
            product_count = len(products)
            message = f"Are you sure you want to publish {product_count} product{'s' if product_count != 1 else ''}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'publish-selected-products',
                            'product_ids': product_ids}
        elif action == 'update-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            message = f"Are you sure you want to update product {self._product_title(product)}?"
            confirm_url = '/admin/dashboard/confirm/'
            confirm_post = {'action': 'update-product',
                            'product_id': product_id}
        else:
            message = 'Are you sure you want to continue with this action?'
            confirm_url = '/admin/dashboard/'
            confirm_post = {}

        return render(request, self.template_name, {
            'page_title': 'Confirm action',
            'page_subtitle': 'Review the action before continuing.',
            'message': message,
            'confirm_url': confirm_url,
            'confirm_post': confirm_post,
        })

    def post(self, request):
        action = request.POST.get('action')
        denied = self._require_action_permission(request, action)
        if denied:
            return denied
        product_id = request.POST.get('product_id')
        product_ids_raw = request.POST.getlist('product_ids')
        product_ids = []
        for value in product_ids_raw:
            product_ids.extend(self._parse_product_ids(value))

        if action == 'delete-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            if product:
                try:
                    DashboardView.delete_product(product)
                    messages.success(request, 'Product deleted.')
                except IntegrityError:
                    messages.error(
                        request,
                        'This product cannot be deleted because it is referenced by an order, cart, or inventory record. Archive it instead.',
                    )
            return redirect('admin-products')

        if action == 'delete-selected-products':
            selected_ids = list(dict.fromkeys(product_ids))
            if not selected_ids:
                messages.error(
                    request, 'Select at least one product to delete.')
                return redirect('admin-products')

            products = list(Product.objects.filter(pk__in=selected_ids))
            deleted = 0
            for product in products:
                try:
                    DashboardView.delete_product(product)
                    deleted += 1
                except IntegrityError:
                    continue

            if deleted:
                messages.success(
                    request, f'{deleted} product{"s" if deleted != 1 else ""} deleted.')
            if deleted != len(products):
                messages.warning(
                    request, 'Some selected products could not be deleted because they are referenced by orders or carts.')
            return redirect('admin-products')

        if action == 'archive-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            if product:
                DashboardView.archive_product(product)
                messages.success(request, 'Product archived.')
            return redirect('admin-products')

        if action == 'publish-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            if product:
                if DashboardView.publish_product(product):
                    messages.success(request, 'Product published.')
                else:
                    messages.info(request, 'Product is already published.')
            return redirect('admin-products')

        if action == 'publish-selected-products':
            selected_ids = list(dict.fromkeys(product_ids))
            if not selected_ids:
                messages.error(
                    request, 'Select at least one product to publish.')
                return redirect('admin-products')

            products = list(Product.objects.filter(pk__in=selected_ids))
            published = 0
            for product in products:
                if DashboardView.publish_product(product):
                    published += 1

            if published:
                messages.success(
                    request,
                    f'{published} product{"s" if published != 1 else ""} published.'
                )
            elif products:
                messages.info(
                    request, 'Selected products are already published.')
            else:
                messages.error(request, 'No products were found to publish.')
            return redirect('admin-products')

        if action == 'update-product' and product_id:
            product = Product.objects.filter(pk=product_id).first()
            if not product:
                messages.error(request, 'Product not found.')
                return redirect('admin-products')

            form = ProductUpdateForm(
                request.POST, request.FILES, product=product)
            if form.is_valid():
                DashboardView.update_product(
                    product, form.cleaned_data, request.FILES.get('image_file'))
                messages.success(request, f'Product {product.name} updated.')
                return redirect('admin-products')

            messages.error(
                request, 'Please correct the product details before confirming.')
            return redirect(f'/admin/dashboard/products/{product_id}/edit/')

        messages.error(request, 'Unknown action.')
        return redirect('admin-dashboard')


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class UnreadNotificationsView(View):
    def get(self, request):
        base = AdminNotification.objects.filter(
            recipient=request.user,
            is_read=False,
        )
        total_unread = base.count()
        notifications = base.order_by('-created_at')[:5]

        results = [
            {
                'id': str(item.id),
                'title': item.title,
                'message': item.message,
                'link': item.link,
                'category': item.category,
                'severity': item.severity,
                'presented': item.presented_at is not None,
                'created_at': item.created_at.isoformat(),
            }
            for item in notifications
        ]

        return JsonResponse({
            'count': total_unread,
            'unread_count': total_unread,
            'results': results,
        })


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class MarkNotificationsPresentedView(View):
    """Atomically claim popup presentation for a set of notification IDs.

    Only the caller that wins the compare-and-set learns that the IDs were
    actually marked ``presented_at``; concurrent pollers/tabs that arrive too
    late get an empty ``presented`` list, so a single unread notification can
    never be re-surfaced after refresh, remount or a later poll.
    """

    def post(self, request):
        try:
            payload = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            payload = {}
        ids = payload.get('ids') or []
        if not isinstance(ids, list):
            return JsonResponse({'ok': False, 'error': 'ids must be a list'},
                                status=400)
        cleaned = [str(raw) for raw in ids[:100] if isinstance(raw, str)]
        if not cleaned:
            return JsonResponse({'ok': True, 'presented': []})

        try:
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
        except Exception:
            logging.getLogger('admin_ui.notify').warning(
                'admin_notification_present_failed recipient=%s ids=%d',
                request.user.pk, len(cleaned), exc_info=True)
            return JsonResponse({'ok': False, 'presented': []}, status=500)

        return JsonResponse({
            'ok': True,
            'presented': [str(nid) for nid in won],
        })


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class AdminNotificationsPageView(View):
    template_name = 'admin_ui/notifications_page.html'

    def get(self, request):
        notifications = AdminNotification.objects.filter(
            recipient=request.user)

        category = (request.GET.get('category') or '').strip()
        severity = (request.GET.get('severity') or '').strip()
        status = (request.GET.get('status') or '').strip()

        if category:
            notifications = notifications.filter(category=category)
        if severity:
            notifications = notifications.filter(severity=severity)
        if status == 'unread':
            notifications = notifications.filter(is_read=False)

        notifications = list(notifications.order_by('-created_at'))
        unread_count = AdminNotification.objects.filter(
            recipient=request.user, is_read=False).count()
        return render(request, self.template_name, {
            'notifications': notifications,
            'unread_count': unread_count,
            'categories': AdminNotification.Category.choices,
            'severities': AdminNotification.Severity.choices,
            'active_filters': {
                'category': category,
                'severity': severity,
                'status': status,
            },
        })


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class MarkAllNotificationsReadView(View):
    def post(self, request):
        updated = AdminNotification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': True, 'unread_count': 0, 'updated': updated})
        return redirect('admin-notifications')


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class MarkNotificationReadView(View):
    def post(self, request, notification_id):
        notification = AdminNotification.objects.filter(
            pk=notification_id,
            recipient=request.user,
        ).first()
        if not notification:
            return JsonResponse({'ok': False}, status=404)

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
        unread_count = AdminNotification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        return JsonResponse({'ok': True, 'unread_count': unread_count})


def _error_detail(exc):
    """First human-readable message out of a Django or DRF ValidationError.

    DRF nests messages under ``detail`` as lists; Django exposes a flat
    ``messages`` sequence. Anything unrecognised yields '' so the caller can
    fall back to its own wording.
    """
    detail = getattr(exc, 'detail', None)
    if detail is None:
        detail = getattr(exc, 'messages', None)
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), None)
    if isinstance(detail, (list, tuple)):
        detail = detail[0] if detail else ''
    return str(detail or '').strip()


@permission_required('orders.confirm')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ApproveOrderPageView(View):
    def post(self, request, order_id):
        order = Order.objects.filter(pk=order_id).first()
        if not order:
            return HttpResponse('Order not found.', status=404)
        try:
            approve_order(order)
        except (DRFValidationError, DjangoValidationError) as exc:
            # The unpaid-order case lives here, but so can a receipt or email
            # validation failure — reporting everything as "only paid orders"
            # sent operators chasing the wrong problem.
            messages.error(
                request, _error_detail(exc) or 'Order could not be approved.')
            return redirect('admin-orders')
        except Exception:
            logger.exception('approve_order failed for order %s', order_id)
            messages.error(
                request,
                'Could not approve this order. The underlying error was '
                'logged — check the server logs.')
            return redirect('admin-orders')
        messages.success(request, 'Order approved.')
        return redirect('admin-orders')


@permission_required('products.import')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductImportPageView(View):
    template_name = 'admin_ui/product_import_page.html'

    def get(self, request):
        return self.render_page(request)

    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if uploaded_file is None:
            messages.error(request, 'Please choose a ZIP package.')
            return self.render_page(request)
        if not str(uploaded_file.name).lower().endswith('.zip'):
            result = import_products_from_file(
                uploaded_file, created_by=request.user)
            AuditLogService.log(
                'file_upload', actor=request.user, category='catalog',
                object_type='file', object_repr=uploaded_file.name,
                metadata={'rows_success': result.rows_success,
                          'rows_failed': result.rows_failed},
                description=f'Legacy product import from {uploaded_file.name}.',
            )
            messages.success(
                request,
                f'Import complete: {result.rows_success} rows succeeded, {result.rows_failed} failed.',
            )
            return self.render_page(request, legacy_result=result)
        try:
            status = request.POST.get('import_status', Product.Status.DRAFT)
            job = BulkProductImportService.create_job(
                uploaded_file, request.user, import_status=status)
            job = BulkProductImportService.validate(job, actor=request.user)
        except BulkImportError as exc:
            messages.error(request, str(exc))
            return self.render_page(request)
        except Exception:
            logger.exception('Admin bulk import upload failed')
            messages.error(request, 'The package could not be uploaded. Please try again.')
            return self.render_page(request)
        messages.success(request, 'Package validated. Review the preview before confirming.')
        return self.render_page(request, job=job)

    def render_page(self, request, job=None, legacy_result=None):
        return render(request, self.template_name, {
            'page_title': 'Bulk Product Import',
            'page_subtitle': 'Upload products, variants and images in one validated package.',
            'job': job_data(job) if job else None,
            'legacy_result': legacy_result,
            'download_template_url': '/admin/dashboard/products/import/download-template/',
            'history_url': '/admin/dashboard/products/import/history/',
            'admin_page': 'bulk-import',
        })


@permission_required('products.import')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductImportTemplateDownloadView(View):
    def get(self, request):
        response = HttpResponse(
            BulkImportTemplateService.to_bytes(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = (
            'attachment; filename="modeza_bulk_import_template.xlsx"'
        )
        return response


@permission_required('products.import')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductImportHistoryPageView(View):
    template_name = 'admin_ui/product_import_history.html'

    def get(self, request):
        jobs = ImportJob.objects.select_related('uploaded_by').all()
        paginator = Paginator(jobs, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, self.template_name, {
            'page_title': 'Bulk Import History',
            'page_subtitle': 'Review previous product package imports and reports.',
            'page': page,
            'paginator': paginator,
            'admin_page': 'bulk-import',
        })


@permission_required('products.import')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductImportReportPageView(View):
    template_name = 'admin_ui/product_import_report.html'

    def get(self, request, job_id):
        job = ImportJob.objects.filter(pk=job_id).select_related('uploaded_by').first()
        if job is None:
            messages.error(request, 'Import job not found.')
            return redirect('admin-product-import-history')
        return render(request, self.template_name, {
            'page_title': f'Import Report {job.pk}',
            'page_subtitle': job.filename,
            'job': job,
            'report': job_data(job),
            'admin_page': 'bulk-import',
        })


@permission_required('products.import')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductImportProgressPageView(View):
    template_name = 'admin_ui/product_import_progress.html'
    terminal_statuses = (
        ImportJob.Status.COMPLETED,
        ImportJob.Status.COMPLETED_WITH_ERRORS,
        ImportJob.Status.FAILED,
    )

    def get(self, request, job_id):
        job = ImportJob.objects.filter(pk=job_id).select_related('uploaded_by').first()
        if job is None:
            messages.error(request, 'Import job not found.')
            return redirect('admin-product-import-history')
        data = job_data(job)
        status_class = 'status-neutral'
        if job.status == ImportJob.Status.COMPLETED:
            status_class = 'status-success'
        elif job.status in (ImportJob.Status.COMPLETED_WITH_ERRORS, ImportJob.Status.FAILED):
            status_class = 'status-danger'
        elif job.status in (ImportJob.Status.PROCESSING, ImportJob.Status.VALIDATING):
            status_class = 'status-warning'
        return render(request, self.template_name, {
            'page_title': 'Import Progress',
            'page_subtitle': job.filename,
            'job': data,
            'status_class': status_class,
            'is_terminal': job.status in self.terminal_statuses,
            'can_start': job.status == ImportJob.Status.READY,
            'import_url': '/admin/dashboard/products/import/',
            'history_url': '/admin/dashboard/products/import/history/',
            'report_url': (
                f'/admin/dashboard/products/import/{job.pk}/report/'
                if job.status in self.terminal_statuses else ''
            ),
            'celery_worker_enabled': settings.CELERY_WORKER_ENABLED,
            'admin_page': 'bulk-import',
        })


class AdminPageView(View):
    template_name = 'admin_ui/admin_page.html'

    COLUMN_KEY_ALIASES = {
        'checkbox': 'checkbox',
        'product image': 'image',
        'product name': 'name',
        'category': 'category',
        'price': 'price',
        'stock': 'stock',
        'status': 'status',
        'actions': 'actions',
        'category image': 'image',
        'category name': 'name',
        'description': 'description',
        'products': 'products',
        'cover image': 'image',
        'collection name': 'name',
        'last updated': 'date',
        'product': 'name',
        'sku': 'sku',
        'current stock': 'stock',
        'low stock threshold': 'threshold',
        'customer': 'customer',
        'email': 'email',
        'order number': 'order',
        'date': 'date',
        'items': 'items',
        'total': 'total',
        'payment status': 'payment',
        'order status': 'status',
        'orders': 'orders',
        'total spent': 'spent',
        'last order': 'last_order',
        'joined date': 'joined',
        'discount name': 'name',
        'code': 'code',
        'type': 'type',
        'value': 'value',
        'usage': 'usage',
        'start date': 'start',
        'end date': 'end',
        'section': 'name',
        'preview': 'preview',
        'banner image': 'image',
        'title': 'title',
        'cta': 'cta',
        'position': 'position',
        'campaign name': 'name',
        'date': 'date',
        'product count': 'count',
        'metric': 'name',
        'period': 'period',
        'report metric': 'name',
        'method name': 'name',
        'delivery estimate': 'estimate',
        'provider': 'name',
        'connection status': 'status',
        'enabled': 'enabled',
        'configure': 'configure',
        'admin': 'name',
        'role': 'role',
        'last active': 'last',
        'account item': 'name',
        'notification': 'name',
        'type': 'type',
        'read': 'read',
    }

    PAGE_MAP = {
        'products': {
            'title': 'Products',
            'subtitle': 'Manage your boutique product catalog.',
            'primary_action': '+ Add Product',
            'primary_url': '/admin/dashboard/products/new/',
            'filters': ['Search products', 'Category filter', 'Collection filter', 'Status filter', 'Stock filter', 'Sort dropdown'],
            'columns': ['Checkbox', 'Product Image', 'Product Name', 'Category', 'Price', 'Stock', 'Status', 'Actions'],
            'empty_title': 'No products found.',
            'empty_description': 'Add Your First Product',
            'rows': [],
        },
        'categories': {
            'title': 'Categories',
            'subtitle': 'Manage product categories.',
            'primary_action': '+ Add Category',
            'primary_url': '/admin/dashboard/categories/new/',
            'filters': ['Search categories'],
            'columns': ['Category Image', 'Category Name', 'Description', 'Products', 'Status', 'Actions'],
            'rows': [],
        },
        'inventory': {
            'title': 'Inventory',
            'subtitle': 'Monitor and manage product inventory.',
            'primary_action': '+ Add Inventory Item',
            'primary_url': '/admin/dashboard/variants/new/',
            'filters': ['Stock status', 'Category', 'Collection'],
            'columns': ['Product', 'SKU', 'Category', 'Current Stock', 'Low Stock Threshold', 'Status', 'Actions'],
            'rows': [],
        },
        'variants': {
            'title': 'Product Variants',
            'subtitle': 'Manage product variations by size, color and stock.',
            'primary_action': '+ Add Variant',
            'primary_url': '/admin/dashboard/variants/new/',
            'filters': ['Search variants', 'Category filter', 'Stock filter'],
            'columns': ['Product', 'SKU', 'Size', 'Color', 'Price', 'Stock', 'Status', 'Actions'],
            'rows': [],
        },
        'orders': {
            'title': 'Orders',
            'subtitle': 'Track and manage customer purchases.',
            'primary_action': '+ Create Order',
            'primary_url': '/admin/dashboard/orders/new/',
            'filters': ['Search order number', 'Search customer', 'Order status', 'Payment status', 'Date filter'],
            'columns': ['Order Number', 'Customer', 'Date', 'Items', 'Total', 'Payment Status', 'Order Status', 'Actions'],
            'rows': [],
        },
        'promotions': {
            'title': 'Promotions',
            'subtitle': 'Create, schedule and monitor discount campaigns.',
            'primary_action': '+ Add Promotion',
            'primary_url': '/admin/dashboard/promotions/new/',
            'filters': ['Search promotions', 'Status filter'],
            'columns': ['Name', 'Type', 'Code', 'Status', 'Starts', 'Ends', 'Usage', 'Discount', 'Actions'],
            'rows': [],
        },
        'customers': {
            'title': 'Customers',
            'subtitle': 'Manage customer accounts.',
            'primary_action': '+ Invite Customer',
            'primary_url': '/admin/dashboard/customers/new/',
            'filters': ['Search customers', 'Customer status', 'Date joined', 'Sort'],
            'columns': ['Customer', 'Email', 'Orders', 'Total Spent', 'Last Order', 'Joined Date', 'Actions'],
            'rows': [],
        },
        'analytics': {
            'title': 'Analytics Overview',
            'subtitle': 'Deeper store business insights.',
            'primary_action': 'Export Report',
            'primary_url': '/admin/dashboard/reports/',
            'filters': ['Date range'],
            'columns': ['Metric', 'Value', 'Period'],
            'rows': [
                {'name': 'Total Revenue', 'value': 'KES 276,000',
                    'period': 'This Year'},
                {'name': 'Total Orders', 'value': '248', 'period': 'This Year'},
                {'name': 'Returning Customers',
                    'value': '34%', 'period': 'This Year'},
            ],
        },
        'reports': {
            'title': 'Sales Reports',
            'subtitle': 'Detailed sales reporting.',
            'primary_action': 'Export Report',
            'primary_url': '/admin/dashboard/reports/export/',
            'filters': ['Date range selector'],
            'columns': ['Report Metric', 'Value'],
            'rows': [
                {'name': 'Gross Sales', 'value': 'KES 482,000'},
                {'name': 'Net Sales', 'value': 'KES 441,200'},
                {'name': 'Refunds', 'value': 'KES 3,400'},
            ],
        },
        'performance': {
            'title': 'Product Performance',
            'subtitle': 'Understand product performance.',
            'primary_action': 'Export Performance',
            'primary_url': '/admin/dashboard/performance/export/',
            'filters': ['Product performance'],
            'columns': ['Product', 'Units Sold', 'Revenue', 'Stock'],
            'rows': [
                {'name': 'MODEZA Silk Wrap Dress', 'units': '34',
                    'revenue': 'KES 163,200', 'stock': '12'},
            ],
        },
        'admin-users': {
            'title': 'Admin Users',
            'subtitle': 'Manage Super Admin accounts.',
            'primary_action': '+ Add Admin Account',
            'primary_url': '/admin/dashboard/staff/create/',
            'filters': ['Role filter', 'Status filter'],
            'columns': ['Admin', 'Email', 'Role', 'Status', 'Last Active', 'Actions'],
            'rows': [],
        },
        'profile': {
            'title': 'My Profile',
            'subtitle': 'Admin profile and account settings.',
            'primary_action': 'Account Settings',
            'primary_url': '/admin/dashboard/profile/settings/',
            'filters': ['Profile'],
            'columns': ['Account Item', 'Value'],
            'rows': [
                {'name': 'My Profile', 'value': 'Active'},
                {'name': 'Change Password', 'value': 'Enabled'},
                {'name': 'Sign Out', 'value': 'Available'},
            ],
        },
    }

    # Which granular permission protects each generic list page.
    PAGE_REQUIRED_PERMISSION = {
        'products': 'products.view',
        'categories': 'categories.view',
        'inventory': 'inventory.view',
        'variants': 'inventory.view',
        'orders': 'orders.view',
        'promotions': 'promotions.view',
        'customers': 'customers.view',
        'admin-users': 'staff.view',
        'analytics': 'reports.view',
        'reports': 'reports.financial',
        'performance': 'reports.view',
        'profile': None,
    }

    @method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
    def dispatch(self, request, *args, **kwargs):
        # Page-level permission check for the generic list pages.
        page = kwargs.get('page', '')
        if page in {'customers', 'admin-users'} and not is_super_admin(request.user):
            return access_denied_response(request)
        required = AdminPageView.PAGE_REQUIRED_PERMISSION.get(page)
        if required and not user_has_permission(request.user, required):
            return access_denied_response(request)
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _normalize_database_row(row):
        return row

    def _render_product_cell(self, column, row):
        safe_column = column.lower().strip()
        if safe_column == 'checkbox':
            return mark_safe('<input type="checkbox" class="admin-row-check" />')
        if safe_column == 'product image':
            image = row.get('image') or ''
            if image:
                return mark_safe(
                    f'<img class="admin-product-thumb" src="{image}" alt="{row.get("name", "Product")}" />'
                )
            return mark_safe('<span class="admin-product-thumb-placeholder">Image</span>')
        if safe_column == 'product name':
            product_id = row.get('id') or ''
            product_name = row.get('name') or 'Unnamed product'
            if product_id:
                return mark_safe(
                    f'<a href="/admin/dashboard/products/{product_id}/" class="admin-product-name-link">{product_name}</a>'
                )
            return mark_safe(product_name)
        if safe_column == 'actions':
            actions = row.get('actions') or []
            product_id = row.get('id') or ''
            options = ['<option selected disabled>Actions</option>']
            route_map = {
                'View': f'/admin/dashboard/products/{product_id}/',
                'Edit': f'/admin/dashboard/products/{product_id}/edit/',
                'Duplicate': f'/admin/dashboard/products/{product_id}/duplicate/',
                'Publish': f'/admin/dashboard/confirm/?action=publish-product&product_id={product_id}',
                'Archive': f'/admin/dashboard/confirm/?action=archive-product&product_id={product_id}',
                'Delete': f'/admin/dashboard/confirm/?action=delete-product&product_id={product_id}',
            }
            for action in actions:
                route = route_map.get(action)
                if route:
                    options.append(
                        f'<option value="{route}">{action}</option>')
            return mark_safe(
                '<select class="admin-action-select" onchange="if (this.value) window.location.href=this.value" aria-label="Actions">'
                + ''.join(options) + '</select>'
            )
        key = self.COLUMN_KEY_ALIASES.get(safe_column, safe_column)
        return row.get(key, '')

    def _render_category_cell(self, column, row):
        safe_column = column.lower().strip()
        if safe_column == 'category image':
            image = row.get('image') or ''
            if image:
                return mark_safe(
                    f'<img class="admin-product-thumb" src="{image}" alt="{row.get("name", "Category")}" />'
                )
            return mark_safe('<span class="admin-product-thumb-placeholder">Image</span>')
        if safe_column == 'actions':
            actions = row.get('actions') or []
            category_id = row.get('id') or ''
            options = ['<option selected disabled>Actions</option>']
            route_map = {
                'Edit': f'/admin/dashboard/categories/{category_id}/edit/',
                'Delete': f'/admin/dashboard/categories/{category_id}/delete/',
            }
            for action in actions:
                route = route_map.get(action)
                if route:
                    options.append(
                        f'<option value="{route}">{action}</option>')
            return mark_safe(
                '<select class="admin-action-select" onchange="if (this.value) window.location.href=this.value" aria-label="Actions">'
                + ''.join(options) + '</select>'
            )
        key = self.COLUMN_KEY_ALIASES.get(safe_column, safe_column)
        return row.get(key, '')

    def _render_order_cell(self, column, row):
        safe_column = column.lower().strip()
        if safe_column == 'actions':
            order_id = row.get('id') or ''
            actions = [
                f'<a class="admin-action-link" href="/admin/dashboard/orders/{order_id}/">View</a>'
            ]
            if row.get('payment') == 'Paid' and row.get('status') != 'Confirmed':
                actions.append(
                    f'<form method="post" action="/admin/dashboard/orders/{order_id}/approve/" style="display:inline;">'
                    '<input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">'
                    '<button type="submit" class="admin-action-link" style="background:#2f3a32;color:#fff;border:none;cursor:pointer;">Approve</button>'
                    '</form>'
                )
            return mark_safe(' '.join(actions))
        if safe_column == 'status':
            value = row.get('status', '')
            css = str(value).lower().replace(' ', '-')
            return mark_safe(f'<span class="status-badge {css}">{value}</span>')
        key = self.COLUMN_KEY_ALIASES.get(safe_column, safe_column)
        return row.get(key, '')

    def _render_promotion_cell(self, column, row):
        safe_column = column.lower().strip()
        if safe_column == 'name':
            promo_id = row.get('id') or ''
            name = row.get('name') or 'Unnamed promotion'
            if promo_id:
                return format_html(
                    '<a href="/admin/dashboard/promotions/{}/" class="admin-product-name-link">{}</a>',
                    promo_id,
                    name,
                )
            return name
        if safe_column == 'status':
            value = row.get('status', '')
            css = str(value).lower().replace(' ', '-')
            return mark_safe(f'<span class="status-badge {css}">{value}</span>')
        if safe_column == 'code':
            value = row.get('code') or '-'
            mode = 'automatic' if value == 'Automatic' else 'coupon'
            return format_html(
                '<span class="promotion-code-chip promotion-code-chip--{}">{}</span>',
                mode, value)
        if safe_column == 'type':
            return format_html('<span class="promotion-type-label">{}</span>', row.get('type', ''))
        if safe_column == 'actions':
            promo_id = row.get('id') or ''
            actions = row.get('actions') or []
            route_map = {
                'View': f'/admin/dashboard/promotions/{promo_id}/',
                'Edit': f'/admin/dashboard/promotions/{promo_id}/edit/',
                'Activate': f'/admin/dashboard/promotions/{promo_id}/activate/',
                'Deactivate': f'/admin/dashboard/promotions/{promo_id}/deactivate/',
                'Duplicate': f'/admin/dashboard/promotions/{promo_id}/duplicate/',
                'Delete': f'/admin/dashboard/promotions/{promo_id}/delete/',
            }
            options = [mark_safe('<option selected disabled>Actions</option>')]
            for action in actions:
                route = route_map.get(action)
                if route:
                    options.append(format_html(
                        '<option value="{}">{}</option>', route, action))
            return format_html(
                '<select class="admin-action-select" onchange="if (this.value) window.location.href=this.value" aria-label="Actions">{}</select>',
                mark_safe(''.join(str(option) for option in options)),
            )
        key = self.COLUMN_KEY_ALIASES.get(safe_column, safe_column)
        return row.get(key, '')

    def _render_page_cell(self, page, column, row):
        if page == 'products':
            return self._render_product_cell(column, row)
        if page == 'categories':
            return self._render_category_cell(column, row)
        if page == 'orders':
            return self._render_order_cell(column, row)
        if page == 'promotions':
            return self._render_promotion_cell(column, row)
        safe_column = column.lower().strip()
        key = self.COLUMN_KEY_ALIASES.get(safe_column, safe_column)
        return row.get(key, '')

    def get(self, request, page='products', *args, **kwargs):
        order_id = kwargs.get('order_id')
        page_data = self.PAGE_MAP.get(page, {
            'title': page.replace('-', ' ').title(),
            'subtitle': 'Manage this admin area.',
            'primary_action': 'Create',
            'primary_url': '/admin/dashboard/',
            'filters': [],
            'columns': ['Name', 'Status'],
            'rows': [],
        })

        if order_id:
            page_data = dict(page_data)
            page_data['selected_order_id'] = str(order_id)
        query = (request.GET.get('q') or request.GET.get(
            'search') or '').strip()

        if page == 'products':
            product_rows = []
            products = Product.objects.select_related(
                'category').prefetch_related('variants').order_by('-created_at')
            if query:
                products = products.filter(
                    Q(name__icontains=query)
                    | Q(description__icontains=query)
                    | Q(slug__icontains=query)
                    | Q(category__name__icontains=query)
                    | Q(variants__sku__icontains=query)
                ).distinct()
            product_status = (request.GET.get('status') or '').strip().upper()
            valid_statuses = {choice[0] for choice in Product.Status.choices}
            if product_status in valid_statuses:
                products = products.filter(status=product_status)
            product_category = (request.GET.get('category') or '').strip()
            if product_category:
                products = products.filter(category__slug=product_category)
            stock_filter = (request.GET.get('stock') or '').strip()
            if stock_filter == 'in-stock':
                products = products.filter(
                    variants__is_active=True,
                    variants__stock_quantity__gt=0,
                ).distinct()
            elif stock_filter == 'out-of-stock':
                products = products.exclude(
                    variants__is_active=True,
                    variants__stock_quantity__gt=0,
                ).distinct()
            product_sort = (request.GET.get('sort') or 'newest').strip()
            if product_sort == 'name':
                products = products.order_by('name', '-created_at')
            elif product_sort == 'price-low':
                products = products.order_by('price_minor', '-created_at')
            elif product_sort == 'price-high':
                products = products.order_by('-price_minor', '-created_at')
            elif product_sort == 'stock-low':
                products = products.annotate(
                    admin_stock_total=Sum('variants__stock_quantity')
                ).order_by('admin_stock_total', '-created_at')
            else:
                product_sort = 'newest'
                products = products.order_by('-created_at')
            product_categories = Category.objects.order_by('name')
            products_page = Paginator(products, 25).get_page(
                request.GET.get('page'))
            for product in products_page.object_list:
                image = Product.normalize_images(product.images)[
                    0] if Product.normalize_images(product.images) else ''
                stock_total = sum(
                    variant.stock_quantity for variant in product.variants.all())
                product_price = Decimal(product.price_minor) / Decimal(100)
                product_rows.append({
                    'checkbox': mark_safe('<input type="checkbox" class="admin-row-check" />'),
                    'id': str(product.pk),
                    'image': image,
                    'name': product.name,
                    'category': product.category.name,
                    'price': f'KES {product_price:.2f}',
                    'stock': str(stock_total),
                    'status': product.get_status_display(),
                    'actions': (
                        ['View', 'Edit', 'Duplicate']
                        + (['Publish'] if product.status ==
                           Product.Status.DRAFT else [])
                        + ['Archive', 'Delete']
                    ),
                })
            page_data = dict(page_data)
            page_data['rows'] = product_rows
            page_data['product_categories'] = product_categories
            page_data['status_choices'] = Product.Status.choices
            page_data['product_status'] = product_status if product_status in valid_statuses else ''
            page_data['product_category'] = product_category
            page_data['product_stock'] = stock_filter if stock_filter in ('in-stock', 'out-of-stock') else ''
            page_data['product_sort'] = product_sort
            page_data['products_query_string'] = urlencode({
                key: value for key, value in {
                    'q': query,
                    'status': page_data['product_status'],
                    'category': page_data['product_category'],
                    'stock': page_data['product_stock'],
                    'sort': product_sort,
                }.items() if value
            })

        if page == 'categories':
            category_rows = []
            categories = Category.objects.annotate(
                product_count=Count('products')).order_by('name')
            if query:
                categories = categories.filter(
                    Q(name__icontains=query) | Q(description__icontains=query)
                )
            for category in categories:
                category_rows.append({
                    'id': str(category.pk),
                    'image': category.image_url or '',
                    'name': category.name,
                    'description': category.description,
                    'products': str(category.product_count),
                    'status': 'Active' if category.is_active else 'Inactive',
                    'actions': ['Edit', 'Delete'],
                })
            page_data = dict(page_data)
            page_data['rows'] = category_rows

        if page == 'inventory':
            inventory_rows = []
            variants = ProductVariant.objects.select_related(
                'product__category').order_by('product__name', 'sku')
            if query:
                variants = variants.filter(
                    Q(sku__icontains=query)
                    | Q(product__name__icontains=query)
                    | Q(product__category__name__icontains=query)
                )
            stock_filter = request.GET.get('stock', '')
            if stock_filter == 'in-stock': variants = variants.filter(stock_quantity__gt=0)
            elif stock_filter == 'low-stock': variants = variants.filter(stock_quantity__gt=0, stock_quantity__lte=3)
            elif stock_filter == 'out-of-stock': variants = variants.filter(stock_quantity__lte=0)
            category_filter = request.GET.get('category', '')
            if category_filter: variants = variants.filter(product__category__slug=category_filter)
            inventory_page = Paginator(variants, 25).get_page(request.GET.get('page'))
            for variant in inventory_page.object_list:
                product = variant.product
                stock = variant.stock_quantity
                inventory_rows.append({
                    'id': str(product.pk),
                    'variant_id': str(variant.pk),
                    'product_id': str(product.pk),
                    'name': product.name,
                    'sku': variant.sku,
                    'category': product.category.name,
                    'stock': str(stock),
                    'threshold': '3',
                    'status': 'Out of Stock' if stock <= 0 else 'Low Stock' if stock <= 3 else 'In Stock',
                    'actions': 'View',
                })
            page_data = dict(page_data)
            page_data['rows'] = inventory_rows
            page_data['list_page'] = inventory_page

        if page == 'variants':
            variant_rows = []
            variants = ProductVariant.objects.select_related(
                'product__category').order_by('product__name', 'size', 'color', 'sku')
            if query:
                variants = variants.filter(
                    Q(sku__icontains=query)
                    | Q(product__name__icontains=query)
                    | Q(product__category__name__icontains=query)
                )
            stock_filter = request.GET.get('stock', '')
            if stock_filter == 'in-stock': variants = variants.filter(stock_quantity__gt=0)
            elif stock_filter == 'low-stock': variants = variants.filter(stock_quantity__gt=0, stock_quantity__lte=3)
            elif stock_filter == 'out-of-stock': variants = variants.filter(stock_quantity__lte=0)
            category_filter = request.GET.get('category', '')
            if category_filter: variants = variants.filter(product__category__slug=category_filter)
            variant_page = Paginator(variants, 25).get_page(request.GET.get('page'))
            for variant in variant_page.object_list:
                product = variant.product
                stock = variant.stock_quantity
                price = Decimal(variant.price_minor or 0) / Decimal(100)
                variant_rows.append({
                    'id': str(variant.pk),
                    'product_id': str(product.pk),
                    'name': product.name,
                    'sku': variant.sku,
                    'size': variant.size or '',
                    'color': variant.color or '',
                    'price': f'KES {price:.2f}',
                    'stock': str(stock),
                    'status': 'Out of Stock' if stock <= 0 else 'Low Stock' if stock <= 3 else 'In Stock',
                    'actions': 'View',
                })
            page_data = dict(page_data)
            page_data['rows'] = variant_rows
            page_data['list_page'] = variant_page

        if page == 'orders':
            order_rows = []
            orders = Order.objects.prefetch_related(
                'payment_intents').order_by('-created_at')
            status = request.GET.get('status')
            payment_status = request.GET.get('payment_status')

            if status:
                orders = orders.filter(status=status)
            if payment_status:
                orders = orders.filter(payment_status=payment_status)
            if query:
                orders = orders.filter(
                    Q(order_number__icontains=query)
                    | Q(customer__fullName__icontains=query)
                    | Q(customer__full_name__icontains=query)
                    | Q(customer__email__icontains=query)
                    | Q(customer__name__icontains=query)
                )
            for order in orders:
                customer = order.customer or {}
                customer_name = (
                    customer.get('fullName')
                    or customer.get('full_name')
                    or customer.get('name')
                    or ' '.join(filter(None, [
                        customer.get('first_name'),
                        customer.get('last_name'),
                    ]))
                    or customer.get('email')
                    or 'Guest customer'
                )
                order_rows.append({
                    'id': str(order.pk),
                    'order': f'#{order.order_number}',
                    'customer': customer_name,
                    'date': order.created_at.strftime('%b %d, %Y'),
                    'item_count': str(order.items.count()),
                    'total': f'KES {Decimal(order.total_minor) / Decimal(100):.2f}',
                    'payment': order.get_payment_status_display(),
                    'status': order.get_status_display(),
                    'can_approve': (
                        order.status == Order.Status.PENDING
                        and is_order_approvable(order)
                    ),
                    'actions': 'View',
                })
            page_data = dict(page_data)
            page_data['rows'] = order_rows

        if page == 'promotions':
            from promotions.models import Promotion, PromotionRedemption
            promo_rows = []
            promos = Promotion.objects.order_by('-priority', '-created_at')
            status_filter = request.GET.get('status') or ''
            if status_filter:
                promos = promos.filter(status=status_filter)
            if query:
                promos = promos.filter(
                    Q(name__icontains=query) | Q(coupon_code__icontains=query)
                )
            for promo in promos:
                used = promo.redemptions.filter(voided=False).count()
                usage = f'{used} / {promo.usage_limit}' if promo.usage_limit else str(used)
                if promo.promotion_type == 'percentage':
                    value = f'{promo.discount_percent:g}%'
                elif promo.promotion_type == 'fixed':
                    value = f'KES {(promo.discount_amount_minor or 0) / 100:,.0f}'
                elif promo.promotion_type == 'free_shipping':
                    value = 'FREE DELIVERY'
                elif promo.promotion_type == 'buy_x_get_y':
                    value = f'Buy {promo.qualifying_quantity} Get {promo.reward_quantity}'
                else:
                    value = f'Buy {promo.qualifying_quantity} Get {promo.reward_discount_percent:g}% off'
                actions = []
                if user_has_permission(request.user, 'promotions.view'):
                    actions.append('View')
                if user_has_permission(request.user, 'promotions.update'):
                    actions.append('Edit')
                    actions.append('Duplicate')
                    actions.append(
                        'Activate' if promo.status != 'active' else 'Deactivate')
                if user_has_permission(request.user, 'promotions.delete'):
                    actions.append('Delete')
                promo_rows.append({
                    'id': str(promo.pk),
                    'name': promo.name,
                    'type': promo.get_promotion_type_display(),
                    'code': promo.coupon_code or ('Automatic' if promo.is_automatic else '-'),
                    'status': promo.get_status_display(),
                    'start': promo.starts_at.strftime('%d %b') if promo.starts_at else '-',
                    'end': promo.ends_at.strftime('%d %b') if promo.ends_at else '-',
                    'usage': usage,
                    'value': value,
                    'actions': actions,
                })
            page_data = dict(page_data)
            page_data['rows'] = promo_rows
            page_data['can_create'] = user_has_permission(
                request.user, 'promotions.create')
            page_data['can_update'] = user_has_permission(
                request.user, 'promotions.update')
            page_data['can_delete'] = user_has_permission(
                request.user, 'promotions.delete')
            if not page_data['can_create']:
                page_data['primary_action'] = ''
            page_data['promo_counts'] = {
                'total': Promotion.objects.count(),
                'active': Promotion.objects.filter(status='active').count(),
                'scheduled': Promotion.objects.filter(status='scheduled').count(),
                'expired': Promotion.objects.filter(status='expired').count(),
                'disabled': Promotion.objects.filter(status='disabled').count(),
                'draft': Promotion.objects.filter(status='draft').count(),
                'automatic': Promotion.objects.filter(is_automatic=True).count(),
                'coupon': Promotion.objects.filter(is_automatic=False).exclude(coupon_code='').count(),
                'redemptions': PromotionRedemption.objects.filter(voided=False).count(),
            }
            page_data['promo_status_choices'] = Promotion.Status.choices
            page_data['promo_status'] = status_filter

        if page == 'customers':
            customer_rows = []
            User = get_user_model()
            users = User.objects.filter(is_staff=False).annotate(
                order_count=Count('orders'),
                total_spent=Sum('orders__total_minor')
            ).order_by('-date_joined')
            if query:
                users = users.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(
                    first_name__icontains=query) | Q(last_name__icontains=query))
            customer_status = request.GET.get('customer_status', '')
            if customer_status == 'active': users = users.filter(is_active=True)
            elif customer_status == 'inactive': users = users.filter(is_active=False)
            date_from, date_to = request.GET.get('date_from'), request.GET.get('date_to')
            if date_from:
                try: users = users.filter(date_joined__date__gte=datetime.fromisoformat(date_from).date())
                except ValueError: date_from = ''
            if date_to:
                try: users = users.filter(date_joined__date__lte=datetime.fromisoformat(date_to).date())
                except ValueError: date_to = ''
            if request.GET.get('sort') == 'oldest': users = users.order_by('date_joined')
            for u in users:
                last_order = u.orders.order_by('-created_at').first()
                spent = Decimal(u.total_spent or 0) / Decimal(100)
                customer_rows.append({
                    'id': str(u.pk),
                    'customer': u.get_full_name() or u.username,
                    'email': u.email,
                    'orders': str(u.order_count),
                    'spent': f'KES {spent:.2f}',
                    'last_order': last_order.created_at.strftime('%b %d, %Y') if last_order else '-',
                    'joined': u.date_joined.strftime('%b %d, %Y'),
                    'actions': 'View'
                })
            page_data = dict(page_data)
            page_data['rows'] = customer_rows

        if page == 'admin-users':
            admin_rows = []
            User = get_user_model()
            admins = (User.objects.filter(is_staff=True)
                      .filter(Q(is_superuser=True)
                              | Q(staff_profile__roles__is_superadmin=True))
                      .distinct()
                      .prefetch_related('staff_profile__roles')
                      .order_by('username'))
            if query:
                admins = admins.filter(
                    Q(username__icontains=query) | Q(email__icontains=query))
            admin_status = request.GET.get('admin_status', '')
            if admin_status == 'active': admins = admins.filter(is_active=True)
            elif admin_status == 'inactive': admins = admins.filter(is_active=False)
            for a in admins:
                admin_rows.append({
                    'id': str(a.pk),
                    'name': a.get_full_name() or a.username,
                    'email': a.email,
                    'role': 'Super Admin',
                    'status': 'Active' if a.is_active else 'Inactive',
                    'last': a.last_login.strftime('%b %d, %Y') if a.last_login else 'Never',
                    'actions': 'View'
                })
            page_data = dict(page_data)
            page_data['rows'] = admin_rows
            page_data['can_assign_roles'] = user_has_permission(
                request.user, 'staff.update')

        if page == 'profile':
            u = request.user
            profile_rows = [
                {'name': 'My Profile', 'value': u.get_full_name() or u.username},
                {'name': 'Email', 'value': u.email},
                {'name': 'Role', 'value': 'Super Admin' if u.is_superuser else 'Staff'},
                {'name': 'Sign Out', 'value': 'Available'},
            ]
            page_data = dict(page_data)
            page_data['rows'] = profile_rows

        if page == 'analytics':
            total_revenue = Decimal(Order.objects.filter(status__in=[
                                    'confirmed', 'processing', 'shipped', 'delivered']).aggregate(s=Sum('total_minor'))['s'] or 0) / Decimal(100)
            total_orders = Order.objects.count()
            analytics_rows = [
                {'name': 'Total Revenue', 'value': f'KES {total_revenue:.2f}',
                    'period': 'All Time'},
                {'name': 'Total Orders', 'value': str(
                    total_orders), 'period': 'All Time'},
            ]
            page_data = dict(page_data)
            page_data['rows'] = analytics_rows

        if page == 'reports':
            gross = Decimal(Order.objects.aggregate(
                s=Sum('total_minor'))['s'] or 0) / Decimal(100)
            refunds = Decimal(Order.objects.filter(payment_status='refunded').aggregate(
                s=Sum('total_minor'))['s'] or 0) / Decimal(100)
            net = gross - refunds
            report_rows = [
                {'name': 'Gross Sales', 'value': f'KES {gross:.2f}'},
                {'name': 'Refunds', 'value': f'KES {refunds:.2f}'},
                {'name': 'Net Sales', 'value': f'KES {net:.2f}'},
            ]
            page_data = dict(page_data)
            page_data['rows'] = report_rows

        if page == 'performance':
            perf_rows = []
            items = OrderItem.objects.values('product__id', 'product_name').annotate(
                units=Sum('quantity'), rev=Sum('line_total_minor')).order_by('-units')[:20]
            for it in items:
                try:
                    p = Product.objects.get(pk=it['product__id'])
                    stock = sum(v.stock_quantity for v in p.variants.all())
                except:
                    stock = 0
                rev = Decimal(it['rev'] or 0) / Decimal(100)
                perf_rows.append({
                    'name': it['product_name'] or 'Unknown',
                    'units': str(it['units']),
                    'revenue': f'KES {rev:.2f}',
                    'stock': str(stock)
                })
            page_data = dict(page_data)
            page_data['rows'] = perf_rows

        columns = page_data.get('columns', [])
        rows = page_data.get('rows', [])
        grid_rows = []

        for row in rows:
            grid_row = []
            for column in columns:
                grid_row.append(self._render_page_cell(page, column, row))
            grid_rows.append(grid_row)

        page_context = {
            'page': page,
            'title': page_data['title'],
            'subtitle': page_data['subtitle'],
            'primary_action': page_data['primary_action'],
            'primary_url': page_data['primary_url'],
            'filters': page_data.get('filters', []),
            'columns': columns,
            'rows': rows,
            'empty_title': page_data.get('empty_title', 'No items found.'),
            'empty_description': page_data.get('empty_description', 'Create the first item to start managing this section.'),
            'can_assign_roles': page_data.get('can_assign_roles', False),
            'products_page': products_page if page == 'products' else None,
            'show_products_pagination': (
                page == 'products' and products_page.paginator.num_pages > 1),
            'list_query_string': urlencode({k: v for k, v in request.GET.items() if k != 'page'}),
            'list_page': page_data.get('list_page'),
            'categories': Category.objects.order_by('name'),
            'can_adjust_inventory': user_has_permission(request.user, 'inventory.adjust'),
            'can_create_variants': (user_has_permission(request.user, 'variants.create')
                                    or user_has_permission(request.user, 'products.update')),
            'can_update_variants': (user_has_permission(request.user, 'variants.update')
                                    or user_has_permission(request.user, 'products.update')),
            'can_delete_variants': (user_has_permission(request.user, 'variants.delete')
                                    or user_has_permission(request.user, 'products.update')),
        }
        if page == 'inventory' and not page_context['can_create_variants']:
            page_context['primary_action'] = ''

        # All other populated admin tables are paged too; the source rows here
        # are bounded to a single view before rendering.
        if page != 'products' and page_context['list_page'] is None and len(page_context['rows']) > 25:
            list_page = Paginator(page_context['rows'], 25).get_page(request.GET.get('page'))
            page_context['list_page'] = list_page
            page_context['rows'] = list(list_page.object_list)

        return render(request, self.template_name, {
            'page_data': page_context,
            'page': page,
            'page_title': page_data['title'],
            'page_subtitle': page_data['subtitle'],
            'page_metric': page,
            'page_primary_action': page_data['primary_action'],
            'page_primary_url': page_data['primary_url'],
            'admin_page_filters': page_data.get('filters', []),
            'admin_page_columns': columns,
            'admin_page_rows': grid_rows,
            'show_search': True,
            'empty_title': page_data.get('empty_title', 'No items found.'),
            'empty_description': page_data.get('empty_description', 'Create the first item to start managing this section.'),
            'data_loaded': True,
            'bulk_actions': page_data.get('bulk_actions', [
                'Publish', 'Archive', 'Delete', 'Assign Category', 'Assign Collection'
            ]) if page == 'products' else [],
            'title': page_data['title'],
            'description': page_data['subtitle'],
            'admin_page': page,
        })


def _build_sales_overview(sales_window_days):
    """Build the daily sales series shared by the page render and refresh API."""
    sales_overview = []
    end_day = timezone.localdate()
    max_total = 0
    for offset in range(sales_window_days):
        day = end_day - timedelta(days=sales_window_days - 1 - offset)
        day_start = timezone.make_aware(
            datetime.combine(day, datetime.min.time()),
            timezone.get_current_timezone(),
        )
        day_end = day_start + timedelta(days=1)
        total_minor = Order.objects.filter(
            created_at__gte=day_start, created_at__lt=day_end).aggregate(
            total=Sum('total_minor'))['total'] or 0
        daily_total = Decimal(total_minor) / Decimal(100)
        max_total = max(max_total, float(daily_total))
        sales_overview.append({
            'label': day.strftime('%a'),
            'value': daily_total,
            'day': day.strftime('%b %d'),
        })
    return sales_overview, max_total


# Geometry for the sales line graph, shared by the page render and refresh API.
SALES_CHART_MIN_WIDTH = 560
SALES_CHART_POINT_SPACING = 28
SALES_CHART_INSET_X = 16
SALES_CHART_PLOT_TOP = 26
SALES_CHART_PLOT_HEIGHT = 200
SALES_CHART_MAX_LABELS = 12


def _build_sales_chart(sales_overview, max_total):
    """Return the SVG geometry used to draw the sales line graph.

    Each point is annotated in place with ``x``/``y`` coordinates so the
    template and the refresh API render the exact same series.
    """
    count = len(sales_overview)
    width = max(
        SALES_CHART_MIN_WIDTH,
        count * SALES_CHART_POINT_SPACING + SALES_CHART_INSET_X * 2,
    )
    span = width - SALES_CHART_INSET_X * 2
    baseline_y = SALES_CHART_PLOT_TOP + SALES_CHART_PLOT_HEIGHT
    label_y = baseline_y + 24
    label_step = max(1, ceil(count / SALES_CHART_MAX_LABELS))
    peak_index = (
        max(range(count), key=lambda i: float(sales_overview[i]['value']))
        if count else None
    )

    coordinates = []
    for index, point in enumerate(sales_overview):
        ratio = (float(point['value']) / max_total) if max_total else 0.0
        ratio = min(1.0, max(0.0, ratio))
        offset = (span * index / (count - 1)) if count > 1 else span / 2
        x = round(SALES_CHART_INSET_X + offset, 2)
        y = round(
            SALES_CHART_PLOT_TOP + (1 - ratio) * SALES_CHART_PLOT_HEIGHT, 2)
        point['x'] = x
        point['y'] = y
        point['show_label'] = index % label_step == 0
        point['is_peak'] = bool(max_total) and index == peak_index
        coordinates.append(f'{x},{y}')

    return {
        'width': width,
        'height': label_y + 12,
        'plot_top': SALES_CHART_PLOT_TOP,
        'plot_top_label': SALES_CHART_PLOT_TOP - 11,
        'baseline_y': baseline_y,
        'label_y': label_y,
        'label_step': label_step,
        'line_points': ' '.join(coordinates),
        'area_points': ' '.join([
            f'{SALES_CHART_INSET_X},{baseline_y}',
            *coordinates,
            f'{width - SALES_CHART_INSET_X},{baseline_y}',
        ]),
    }


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class DashboardView(View):
    template_name = 'admin_ui/dashboard.html'

    def get(self, request):
        return self.render_dashboard(request)

    def post(self, request):
        action = request.POST.get('action')
        required_permissions = {
            'create-product': 'products.create',
            'update-product': 'products.update',
            'archive-product': 'products.update',
            'publish-product': 'products.update',
            'publish-selected-products': 'products.update',
            'delete-product': 'products.delete',
            'delete-selected-products': 'products.delete',
            'adjust-stock': 'inventory.adjust',
            'delete-category': 'categories.delete',
        }
        required = required_permissions.get(action)
        if required and not user_has_permission(request.user, required):
            return access_denied_response(request)
        if action == 'create-product':
            form = ProductCreateForm(request.POST, request.FILES)
            if form.is_valid():
                metadata = ProductGenerationService.generate_product_metadata(
                    form.cleaned_data['name'])
                data = {**form.cleaned_data, **(metadata or {})}
                self.create_product(data,
                                    request.FILES.get('image_file'))
                messages.success(request, 'Product and first variant created.')
                return redirect('admin-products')
            return self.render_dashboard(request, product_form=form)
        if action == 'update-product':
            product = Product.objects.filter(
                pk=request.POST.get('product_id')).first()
            if not product:
                messages.error(request, 'Product not found.')
                return redirect('admin-products')
            form = ProductUpdateForm(
                request.POST, request.FILES, product=product)
            if form.is_valid():
                self.update_product(product, form.cleaned_data,
                                    request.FILES.get('image_file'))
                messages.success(request, 'Product updated.')
                return redirect('admin-products')
            return self.render_dashboard(request, product_form=form)
        if action == 'archive-product':
            product = Product.objects.filter(
                pk=request.POST.get('product_id')).first()
            if not product:
                messages.error(request, 'Product not found.')
                return redirect('admin-products')
            self.archive_product(product)
            messages.success(request, 'Product archived.')
            return redirect('admin-products')
        if action == 'publish-product':
            product = Product.objects.filter(
                pk=request.POST.get('product_id')).first()
            if not product:
                messages.error(request, 'Product not found.')
                return redirect('admin-products')
            if self.publish_product(product):
                messages.success(request, 'Product published.')
            else:
                messages.info(request, 'Product is already published.')
            return redirect('admin-products')
        if action == 'publish-selected-products':
            raw_ids = request.POST.getlist('product_ids')
            selected_ids = []
            for raw in raw_ids:
                selected_ids.extend(
                    [part.strip() for part in raw.split(',') if part.strip()]
                )
            selected_ids = list(dict.fromkeys(selected_ids))
            if not selected_ids:
                messages.error(
                    request, 'Select at least one product to publish.')
                return redirect('admin-products')

            products = list(Product.objects.filter(pk__in=selected_ids))
            if not products:
                messages.error(
                    request, 'No products were found to publish.')
                return redirect('admin-products')

            published = sum(
                1 for product in products if self.publish_product(product))
            if published:
                messages.success(
                    request,
                    f'{published} product{"s" if published != 1 else ""} published.'
                )
            else:
                messages.info(
                    request, 'Selected products are already published.')
            return redirect('admin-products')
        if action == 'delete-product':
            product = Product.objects.filter(
                pk=request.POST.get('product_id')).first()
            if not product:
                messages.error(request, 'Product not found.')
                return redirect('admin-products')
            try:
                self.delete_product(product)
            except IntegrityError:
                messages.error(
                    request,
                    'This product cannot be deleted because it is referenced by an order, cart, or inventory record. Archive it instead.',
                )
            else:
                messages.success(request, 'Product deleted.')
            return redirect('admin-products')
        if action == 'delete-selected-products':
            raw_ids = request.POST.getlist('product_ids')
            selected_ids = []
            for raw in raw_ids:
                selected_ids.extend(
                    [part.strip() for part in raw.split(',') if part.strip()]
                )
            selected_ids = list(dict.fromkeys(selected_ids))
            if not selected_ids:
                messages.error(
                    request, 'Select at least one product to delete.')
                return redirect('admin-products')

            products = list(Product.objects.filter(pk__in=selected_ids))
            if not products:
                messages.error(request, 'No products were found to delete.')
                return redirect('admin-products')

            deleted = 0
            for product in products:
                try:
                    self.delete_product(product)
                    deleted += 1
                except IntegrityError:
                    continue
            if deleted:
                messages.success(
                    request,
                    f'{deleted} product{"s" if deleted != 1 else ""} deleted.'
                )
            if deleted != len(products):
                messages.warning(
                    request,
                    'Some selected products could not be deleted because they are referenced by orders or carts.'
                )
            return redirect('admin-products')
        if action == 'adjust-stock':
            form = StockAdjustmentForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                adjust_stock(data['variant'].id, data['delta'],
                             data['reason'], request.user)
                messages.success(request, 'Inventory updated.')
                return redirect('admin-dashboard')
            return self.render_dashboard(request, stock_form=form)
        if action == 'delete-category':
            category = Category.objects.filter(
                pk=request.POST.get('category_id')).first()
            if not category:
                messages.error(request, 'Category not found.')
                return redirect('admin-dashboard')
            try:
                category.delete()
            except IntegrityError:
                messages.error(
                    request,
                    'This category cannot be deleted because products still use it. Edit or move those products first.',
                )
            else:
                _audit_catalog('delete', category)
                messages.success(request, 'Category deleted.')
            return redirect('admin-dashboard')
        messages.error(request, 'Unknown dashboard action.')
        return redirect('admin-dashboard')

    def render_dashboard(self, request, product_form=None, stock_form=None):
        products = Product.objects.select_related(
            'category').prefetch_related('variants')
        categories = Category.objects.annotate(product_count=Count('products'))
        variants = ProductVariant.objects.select_related(
            'product').order_by('product__name', 'sku')

        range_value = request.GET.get('range', '7')
        try:
            sales_window_days = int(range_value)
        except (TypeError, ValueError):
            sales_window_days = 7
        sales_window_days = max(7, min(sales_window_days, 90))

        # Core dashboard metrics and lightweight activity feeds.
        # The total revenue KPI must be derived from the database by excluding pending/cancelled
        # order rows, so only approved, active revenue streams are counted.
        total_revenue_minor = Order.objects.exclude(
            status=Order.Status.PENDING
        ).exclude(
            status=Order.Status.CANCELLED
        ).aggregate(
            total_revenue=Sum('total_minor')
        ).get('total_revenue') or 0
        total_revenue_kes = Decimal(total_revenue_minor) / Decimal('100')

        # A real pending-revenue KPI must read the live Order table directly from the database.
        pending_revenue_minor = Order.objects.filter(
            status=Order.Status.PENDING
        ).aggregate(
            pending_revenue=Sum('total_minor')
        ).get('pending_revenue') or 0
        pending_revenue_kes = Decimal(pending_revenue_minor) / Decimal('100')

        total_orders = Order.objects.count()
        total_customers = get_user_model().objects.filter(is_staff=False).count()
        low_stock_count = ProductVariant.objects.filter(
            stock_quantity__lte=3).count()

        sales_overview, sales_peak = _build_sales_overview(sales_window_days)
        sales_chart = _build_sales_chart(sales_overview, sales_peak)

        return render(request, self.template_name, {
            'products': products,
            'categories': categories,
            'categories_count': Category.objects.filter(is_active=True).count(),
            'total_stock': sum(variant.stock_quantity for variant in variants),
            'total_products': products.count(),
            'low_stock_count': low_stock_count,
            'product_form': product_form or ProductCreateForm(),
            'stock_form': stock_form or StockAdjustmentForm(),
            'total_revenue_kes': total_revenue_kes,
            'pending_revenue_kes': pending_revenue_kes,
            'total_orders': total_orders,
            'total_customers': total_customers,
            'orders_needing_attention': Order.objects.filter(
                status=Order.Status.PENDING
            ).filter(
                Q(payment_status=Order.PaymentStatus.PAID)
                | Q(payment_method__in=['cash_on_delivery', 'pay_on_delivery'])
                | Q(payment_intents__method=PaymentIntent.Method.MPESA,
                    payment_intents__status=PaymentIntent.Status.SIMULATED)
            ).distinct().count(),
            'sales_overview': sales_overview,
            'sales_chart': sales_chart,
            'sales_peak_kes': sales_peak,
            'sales_period_total_kes': sum(
                (point['value'] for point in sales_overview), Decimal('0')),
            'sales_range': sales_window_days,
            'storefront_url': settings.FRONTEND_ORIGIN,
            'admin_page': 'dashboard',
        })

    @staticmethod
    def sync_image_fields(product, image_path):
        image_path = (image_path or '').strip()
        if not image_path:
            return product

        existing_images = [img for img in Product.normalize_images(
            product.images) if img and img != image_path]
        product.images = [image_path, *existing_images]
        return product

    @staticmethod
    @transaction.atomic
    def create_product(data, uploaded_image=None):
        image_path = ''
        if uploaded_image:
            file_name = uploaded_image.name
            safe_name = f"{uuid.uuid4()}_{file_name}"
            saved_path = default_storage.save(
                f'products/{safe_name}', uploaded_image)
            image_path = default_storage.url(saved_path)

        product = Product.objects.create(
            category=data['category'],
            name=data['name'],
            slug=data['slug'],
            description=data['description'],
            price_minor=int(
                (data['price'] * Decimal('100')).quantize(Decimal('1'))),
            status=data['status'],
            images=[image_path] if image_path else [],
        )
        ProductVariant.objects.create(
            product=product,
            sku=data['sku'] or ProductGenerationService.generate_internal_code(
                data['name']),
            size=data['size'],
            color=data['color'],
            stock_quantity=data['stock_quantity'],
        )
        _audit_catalog(
            'create', product,
            status_code=201,
            metadata={'has_image': bool(image_path),
                      'stock_quantity': data['stock_quantity']},
        )

    @staticmethod
    @transaction.atomic
    def update_product(product, data, uploaded_image=None):
        image_path = ''
        if uploaded_image:
            file_name = uploaded_image.name
            safe_name = f"{uuid.uuid4()}_{file_name}"
            saved_path = default_storage.save(
                f'products/{safe_name}', uploaded_image)
            image_path = default_storage.url(saved_path)

        before = (product.name, product.status, product.price_minor)
        product.category = data['category']
        product.name = data['name']
        product.slug = data['slug']
        product.description = data['description']
        product.price_minor = int(
            (data['price'] * Decimal('100')).quantize(Decimal('1')))
        product.status = data['status']

        if image_path:
            DashboardView.sync_image_fields(product, image_path)

        product.save()
        _audit_catalog(
            'update', product,
            metadata={'changed': {
                'name': {'from': before[0], 'to': product.name},
                'status': {'from': before[1], 'to': product.status},
                'price_minor': {'from': before[2], 'to': product.price_minor},
            }, 'has_image': bool(image_path)},
        )

    @staticmethod
    @transaction.atomic
    def archive_product(product):
        previous = product.status
        product.status = Product.Status.ARCHIVED
        product.save(update_fields=['status', 'updated_at'])
        _audit_catalog(
            'update', product,
            metadata={'status_changed': {'from': previous,
                                         'to': product.status}},
        )

    @staticmethod
    @transaction.atomic
    def publish_product(product):
        """Move a product live (ACTIVE + visible); no-op when already published."""
        previous = product.status
        already_published = (
            previous == Product.Status.ACTIVE and product.is_active)
        if already_published:
            return False
        product.status = Product.Status.ACTIVE
        product.is_active = True
        product.save(update_fields=['status', 'is_active', 'updated_at'])
        _audit_catalog(
            'update', product,
            metadata={'status_changed': {'from': previous,
                                         'to': product.status}},
        )
        return True

    @staticmethod
    @transaction.atomic
    def delete_product(product):
        image_paths = Product.normalize_images(product.images)
        _audit_catalog('delete', product)
        product.delete()
        for image_path in image_paths:
            storage_path = object_key_from_url(image_path) or image_path.removeprefix(
                settings.MEDIA_URL)
            if storage_path:
                default_storage.delete(storage_path)


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class DashboardDataView(View):
    """Silent-refresh endpoint powering the dashboard's live KPI updates."""

    def get(self, request):
        range_value = request.GET.get('range', '7')
        try:
            sales_window_days = int(range_value)
        except (TypeError, ValueError):
            sales_window_days = 7
        sales_window_days = max(7, min(sales_window_days, 90))

        total_revenue_kes = (Decimal(
            Order.objects.exclude(status=Order.Status.PENDING).exclude(
                status=Order.Status.CANCELLED
            ).aggregate(total=Sum('total_minor')).get('total') or 0
        ) / Decimal('100'))
        pending_revenue_kes = (Decimal(
            Order.objects.filter(status=Order.Status.PENDING).aggregate(
                total=Sum('total_minor')).get('total') or 0
        ) / Decimal('100'))

        total_orders = Order.objects.count()
        total_customers = get_user_model().objects.filter(is_staff=False).count()
        total_products = Product.objects.count()
        orders_needing_attention = Order.objects.filter(
            status=Order.Status.PENDING).filter(
            Q(payment_status=Order.PaymentStatus.PAID)
            | Q(payment_method__in=['cash_on_delivery', 'pay_on_delivery'])
            | Q(payment_intents__method=PaymentIntent.Method.MPESA,
                payment_intents__status=PaymentIntent.Status.SIMULATED)
        ).distinct().count()

        low_stock_count = ProductVariant.objects.filter(
            stock_quantity__lte=3).count()

        sales_overview, sales_peak = _build_sales_overview(sales_window_days)
        sales_chart = _build_sales_chart(sales_overview, sales_peak)

        payload = {
            'kpis': {
                'revenue': f'KES {total_revenue_kes:.0f}',
                'pending_revenue': f'KES {pending_revenue_kes:.0f}',
                'orders': total_orders,
                'customers': total_customers,
                'products': total_products,
                'low_stock': low_stock_count,
                'attention_orders': orders_needing_attention,
            },
            'sales_period_total': f'KES {sum((point["value"] for point in sales_overview), Decimal("0")):.0f}',
            'sales_peak': f'KES {sales_peak:.0f}',
            'sales_chart': sales_chart,
            'overview': [{
                'label': point['label'],
                'day': point['day'],
                'value': f"{point['value']:.2f}",
                'x': point['x'],
                'y': point['y'],
                'show_label': point['show_label'],
                'is_peak': point['is_peak'],
            } for point in sales_overview],
            'updated_at': timezone.now().isoformat(),
        }
        return JsonResponse(payload)


@permission_required('categories.create')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class CategoryCreatePageView(View):
    template_name = 'admin_ui/category_form_page.html'

    def get(self, request):
        return self.render_form(request, CategoryForm())

    def post(self, request):
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            _audit_catalog('create', category, status_code=201)
            messages.success(request, 'Category created.')
            return redirect('admin-dashboard')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'Add a category',
            'page_subtitle': 'Create a collection for organizing your products.',
            'submit_label': 'Add category',
        })


@permission_required('categories.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class CategoryEditPageView(View):
    template_name = 'admin_ui/category_form_page.html'

    def get_category(self, category_id):
        return Category.objects.filter(pk=category_id).first()

    def get(self, request, category_id):
        category = self.get_category(category_id)
        if not category:
            messages.error(request, 'Category not found.')
            return redirect('admin-dashboard')
        return self.render_form(request, CategoryForm(instance=category), category)

    def post(self, request, category_id):
        category = self.get_category(category_id)
        if not category:
            messages.error(request, 'Category not found.')
            return redirect('admin-dashboard')
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            _audit_catalog('update', category)
            messages.success(request, 'Category updated.')
            return redirect('admin-dashboard')
        return self.render_form(request, form, category)

    def render_form(self, request, form, category=None):
        return render(request, self.template_name, {
            'form': form,
            'category': category,
            'page_title': 'Edit category',
            'page_subtitle': 'Update the collection details shown to customers.',
            'submit_label': 'Save changes',
        })


@permission_required('categories.delete')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class CategoryDeletePageView(View):
    def get(self, request, category_id):
        category = Category.objects.filter(pk=category_id).first()
        if not category:
            messages.error(request, 'Category not found.')
            return redirect('admin-dashboard')
        try:
            category.delete()
        except IntegrityError:
            messages.error(request,
                           'This category cannot be deleted because products still use it. Edit or move those products first.')
        else:
            _audit_catalog('delete', category)
            messages.success(request, 'Category deleted.')
        return redirect('admin-dashboard')


def _audit_promotion(action, promo, metadata=None, status_code=None):
    AuditLogService.log(
        action,
        object_type='promotion',
        object_id=promo.pk,
        object_repr=promo.name,
        category='orders',
        metadata=metadata,
        status_code=status_code,
        description=f'{action}: promotion {promo.name}.',
    )


@permission_required('promotions.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class PromotionDetailPageView(View):
    template_name = 'admin_ui/promotion_detail_page.html'

    def get(self, request, promo_id):
        from promotions.models import Promotion

        promo = Promotion.objects.filter(pk=promo_id).first()
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        value = {
            'percentage': f'{promo.discount_percent:g}% off',
            'fixed': f'KES {(promo.discount_amount_minor or 0) / 100:,.2f} off',
            'free_shipping': 'Free shipping',
            'buy_x_get_y': (
                f'Buy {promo.qualifying_quantity}, get {promo.reward_quantity} free'),
            'buy_x_get_pct': (
                f'Buy {promo.qualifying_quantity}, get '
                f'{promo.reward_discount_percent:g}% off {promo.reward_quantity}'),
        }.get(promo.promotion_type, promo.get_promotion_type_display())
        details = [
            ('Status', promo.get_status_display()),
            ('Offer', value),
            ('Coupon', promo.coupon_code or (
                'Automatic' if promo.is_automatic else 'None')),
            ('Starts', timezone.localtime(promo.starts_at).strftime('%b %d, %Y %H:%M')
             if promo.starts_at else 'Immediately'),
            ('Ends', timezone.localtime(promo.ends_at).strftime('%b %d, %Y %H:%M')
             if promo.ends_at else 'No expiry'),
            ('Minimum order', f'KES {(promo.minimum_order_value_minor or 0) / 100:,.2f}'),
            ('Usage', str(promo.redemptions.filter(voided=False).count())),
        ]
        return render(request, self.template_name, {
            'promo': promo,
            'details': details,
            'can_update': user_has_permission(request.user, 'promotions.update'),
            'can_delete': user_has_permission(request.user, 'promotions.delete'),
        })


@permission_required('promotions.create')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class PromotionCreatePageView(View):
    template_name = 'admin_ui/promotion_form_page.html'

    def get(self, request):
        from .forms import PromotionForm
        return self.render_form(request, PromotionForm())

    def post(self, request):
        from .forms import PromotionForm
        from promotions.models import normalize_coupon_code
        form = PromotionForm(request.POST)
        if form.is_valid():
            normalized = normalize_coupon_code(form.cleaned_data.get('coupon_code') or '')
            if normalized and _promo_code_taken(normalized):
                form.add_error('coupon_code', 'An active promotion already uses this code.')
                return self.render_form(request, form)
            form.instance.created_by = request.user
            form.instance.updated_by = request.user
            promo = form.save()
            if promo.status == 'active':
                from promotions.notifications import notify_promotion_customers
                notify_promotion_customers(promo)
            _audit_promotion('promotion_created', promo, status_code=201)
            messages.success(request, 'Promotion created.')
            return redirect('admin-promotions')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'Add a promotion',
            'page_subtitle': 'Define the discount, eligibility, schedule and limits.',
            'submit_label': 'Add promotion',
        })


@permission_required('promotions.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class PromotionEditPageView(View):
    template_name = 'admin_ui/promotion_form_page.html'

    def get_promo(self, promo_id):
        from promotions.models import Promotion
        return Promotion.objects.filter(pk=promo_id).first()

    def get(self, request, promo_id):
        from .forms import PromotionForm
        promo = self.get_promo(promo_id)
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        return self.render_form(request, PromotionForm(instance=promo), promo)

    def post(self, request, promo_id):
        from .forms import PromotionForm
        from promotions.models import normalize_coupon_code
        promo = self.get_promo(promo_id)
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        old_code = promo.coupon_code_normalized
        old_status = promo.status
        form = PromotionForm(request.POST, instance=promo)
        if form.is_valid():
            normalized = normalize_coupon_code(form.cleaned_data.get('coupon_code') or '')
            if normalized and _promo_code_taken(normalized, exclude_pk=promo.pk):
                form.add_error('coupon_code', 'An active promotion already uses this code.')
                return self.render_form(request, form, promo)
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            form.save()
            if old_status != 'active' and updated.status == 'active':
                from promotions.notifications import notify_promotion_customers
                notify_promotion_customers(updated)
            if old_code != updated.coupon_code_normalized:
                _audit_promotion('promotion_code_changed', updated,
                                 metadata={'from': old_code, 'to': updated.coupon_code_normalized})
            _audit_promotion('promotion_updated', updated)
            messages.success(request, 'Promotion updated.')
            return redirect('admin-promotions')
        return self.render_form(request, form, promo)

    def render_form(self, request, form, promo=None):
        return render(request, self.template_name, {
            'form': form,
            'promo': promo,
            'page_title': 'Edit promotion',
            'page_subtitle': 'Update the discount, eligibility, schedule and limits.',
            'submit_label': 'Save changes',
        })


def _promo_code_taken(normalized, exclude_pk=None):
    from promotions.models import Promotion
    qs = Promotion.objects.filter(coupon_code_normalized=normalized).exclude(
        status__in=[Promotion.Status.DISABLED, Promotion.Status.EXPIRED])
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


@permission_required('promotions.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class PromotionActionPageView(View):
    def get(self, request, promo_id, action):
        from promotions.models import Promotion
        promo = Promotion.objects.filter(pk=promo_id).first()
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        if action == 'activate':
            if not promo.ends_at:
                messages.error(
                    request,
                    'Set an end date before publishing this promotion.',
                )
                return redirect('admin-promotions')
            was_active = promo.status == Promotion.Status.ACTIVE
            promo.status = Promotion.Status.ACTIVE
            promo.save(update_fields=['status', 'updated_at'])
            if not was_active:
                from promotions.notifications import notify_promotion_customers
                notify_promotion_customers(promo)
            _audit_promotion('promotion_activated', promo)
            messages.success(request, f'Promotion "{promo.name}" activated.')
        elif action == 'deactivate':
            promo.status = Promotion.Status.DISABLED
            promo.save(update_fields=['status', 'updated_at'])
            _audit_promotion('promotion_deactivated', promo)
            messages.success(request, f'Promotion "{promo.name}" deactivated.')
        elif action == 'duplicate':
            from copy import deepcopy
            clone = deepcopy(promo)
            clone.pk = None
            clone.name = f'{promo.name} (copy)'
            clone.coupon_code = ''
            clone.coupon_code_normalized = ''
            clone.status = Promotion.Status.DISABLED
            clone.save()
            for link in promo.promo_products.all():
                promo.promo_products.model.objects.create(promotion=clone, product=link.product)
            for link in promo.promo_categories.all():
                promo.promo_categories.model.objects.create(promotion=clone, category=link.category)
            for link in promo.promo_variants.all():
                promo.promo_variants.model.objects.create(promotion=clone, variant=link.variant)
            _audit_promotion('promotion_created', clone, metadata={'duplicated_from': str(promo.pk)})
            messages.success(request, f'Promotion duplicated as "{clone.name}".')
        else:
            messages.error(request, 'Unknown promotion action.')
        return redirect('admin-promotions')


@permission_required('promotions.delete')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class PromotionDeletePageView(View):
    template_name = 'admin_ui/promotion_delete_page.html'

    def get_promo(self, promo_id):
        from promotions.models import Promotion
        return Promotion.objects.filter(pk=promo_id).first()

    def get(self, request, promo_id):
        promo = self.get_promo(promo_id)
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        return render(request, self.template_name, {'promo': promo})

    def post(self, request, promo_id):
        promo = self.get_promo(promo_id)
        if not promo:
            messages.error(request, 'Promotion not found.')
            return redirect('admin-promotions')
        name = promo.name
        try:
            promo.delete()
        except ProtectedError:
            messages.error(
                request,
                'This promotion has redemptions and cannot be deleted. Deactivate it instead.',
            )
        else:
            _audit_promotion('promotion_deleted', promo)
            messages.success(request, f'Promotion "{name}" deleted.')
        return redirect('admin-promotions')


@permission_required('products.create')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductCreatePageView(View):
    template_name = 'admin_ui/product_form_page.html'

    def get(self, request):
        return self.render_form(request, ProductCreateForm())

    def post(self, request):
        form = ProductCreateForm(request.POST, request.FILES)
        if form.is_valid():
            metadata = ProductGenerationService.generate_product_metadata(
                form.cleaned_data['name'])
            data = {**form.cleaned_data, **(metadata or {})}
            DashboardView.create_product(data, request.FILES.get('image_file'))
            messages.success(request, 'Product and first variant created.')
            return redirect('admin-dashboard')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'Add a product',
            'page_subtitle': 'Create a new product and first inventory entry.',
            'submit_label': 'Add to shop',
        })


@permission_required('products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductEditPageView(View):
    template_name = 'admin_ui/product_form_page.html'

    def get(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-dashboard')
        _audit_catalog(
            'product_viewed', product,
            metadata={'surface': 'admin_product_edit'},
        )
        form = ProductUpdateForm(
            initial={
                'product_id': product.pk,
                'name': product.name,
                'slug': product.slug,
                'category': product.category_id,
                'description': product.description,
                'price': product.price_display,
                'status': product.status,
            },
            product=product,
        )
        return self.render_form(request, form, product)

    def post(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        form = ProductUpdateForm(request.POST, request.FILES, product=product)
        if form.is_valid():
            DashboardView.update_product(product, form.cleaned_data,
                                         request.FILES.get('image_file'))
            messages.success(request, 'Product updated.')
            return redirect('admin-products')
        return self.render_form(request, form, product)

    def render_form(self, request, form, product=None):
        return render(request, self.template_name, {
            'form': form,
            'product': product,
            'page_title': 'Edit product',
            'page_subtitle': 'Adjust product details and update the item description.',
            'submit_label': 'Save changes',
            'show_archive': bool(product),
        })


@permission_required('products.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductDetailPageView(View):
    template_name = 'admin_ui/product_detail_page.html'

    def get(self, request, product_id):
        product = Product.objects.select_related('category').prefetch_related(
            'product_images', 'variants__variant_images').filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-dashboard')
        _audit_catalog(
            'product_viewed', product,
            metadata={'surface': 'admin_product_detail'},
        )
        variant_rows = [
            {
                'variant': variant,
                'price': (
                    f'KES {Decimal(variant.price_minor) / Decimal(100):.2f}'
                    if variant.price_minor is not None else 'Product price'),
            }
            for variant in product.variants.order_by('sku')
        ]
        activity = AuditLog.objects.select_related('actor').filter(
            object_type__in=('product', 'productvariant'),
            object_id=str(product.pk),
        )[:40]
        activity = decorate_audit_logs(list(activity))
        return render(request, self.template_name, {
            'product': product,
            'variant_rows': variant_rows,
            'activity_logs': activity,
            'logs': activity,
            'page_title': 'Product Details',
            'page_subtitle': product.name,
            'page_primary_action': 'Edit Product',
            'page_primary_url': f'/admin/dashboard/products/{product.id}/edit/',
        })


@permission_required('variants.create', 'products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class VariantProductPickerView(View):
    """Choose a product that a new variant should belong to."""

    template_name = 'admin_ui/variant_picker_page.html'

    def get(self, request):
        query = (request.GET.get('q') or '').strip()
        products = Product.objects.select_related('category').prefetch_related(
            'variants').order_by('name')
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(sku__icontains=query)
                | Q(category__name__icontains=query)
            )
        product_rows = []
        for product in products:
            variants = product.variants.all()
            normalized_images = Product.normalize_images(product.images)
            product_rows.append({
                'id': str(product.pk),
                'name': product.name,
                'image': normalized_images[0] if normalized_images else '',
                'category': product.category.name if product.category else '—',
                'variant_count': variants.count(),
                'stock': str(sum(v.stock_quantity for v in variants)),
                'status': product.get_status_display(),
                'new_variant_url': f'/admin/dashboard/products/{product.pk}/variants/new/',
            })
        return render(request, self.template_name, {
            'product_rows': product_rows,
            'query': query,
            'product_count': products.count(),
            'page_title': 'Add Variant',
            'page_subtitle': 'Choose a product to add a new variant to.',
            'admin_page': 'variants',
        })


@permission_required('variants.create', 'products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductVariantCreatePageView(View):
    template_name = 'admin_ui/variant_form_page.html'

    def get_product(self, product_id):
        return Product.objects.filter(pk=product_id).first()

    def get(self, request, product_id):
        product = self.get_product(product_id)
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        return self.render_form(request, product, ProductVariantForm(product=product))

    def post(self, request, product_id):
        product = self.get_product(product_id)
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        form = ProductVariantForm(request.POST, product=product)
        if form.is_valid():
            data = form.cleaned_data
            variant = ProductVariant.objects.create(
                product=product,
                sku=data['sku'],
                size=data['size'],
                color=data['color'],
                color_hex=data['color_hex'],
                price_minor=(int(data['price'] * 100)
                             if data['price'] is not None else None),
                stock_quantity=data['stock_quantity'],
                is_active=data['is_active'],
            )
            _audit_catalog('create', variant, metadata={
                           'product_id': str(product.pk)})
            messages.success(request, 'Variant added.')
            return redirect('admin-product-detail', product_id=product.pk)
        return self.render_form(request, product, form)

    def render_form(self, request, product, form):
        return render(request, self.template_name, {
            'form': form,
            'product': product,
            'page_title': 'Add variant',
            'page_subtitle': f'Add a sellable option to {product.name}.',
            'submit_label': 'Add variant',
        })


@permission_required('variants.create', 'products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductVariantBulkCreatePageView(View):
    template_name = 'admin_ui/variant_bulk_form_page.html'

    def get_product(self, product_id):
        return Product.objects.filter(pk=product_id).first()

    def get(self, request, product_id):
        product = self.get_product(product_id)
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        return self.render_form(request, product, ProductVariantBulkForm(product=product))

    def post(self, request, product_id):
        product = self.get_product(product_id)
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        form = ProductVariantBulkForm(request.POST, product=product)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                for sku, size, quantity in data['variant_specs']:
                    variant = ProductVariant.objects.create(
                        product=product,
                        sku=sku,
                        size=size,
                        color=data['color'],
                        color_hex=data['color_hex'],
                        price_minor=(int(data['price'] * 100)
                                     if data['price'] is not None else None),
                        stock_quantity=quantity,
                        is_active=True,
                    )
                    _audit_catalog('create', variant, metadata={
                        'product_id': str(product.pk), 'bulk': True})
            messages.success(request, 'Variants added.')
            return redirect('admin-product-detail', product_id=product.pk)
        return self.render_form(request, product, form)

    def render_form(self, request, product, form):
        return render(request, self.template_name, {
            'form': form,
            'product': product,
            'page_title': 'Add variants',
            'page_subtitle': f'Add sizes and quantities for {product.name}.',
            'submit_label': 'Add variants',
        })


@permission_required('variants.update', 'products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductVariantEditPageView(View):
    template_name = 'admin_ui/variant_form_page.html'

    def get_variant(self, product_id, variant_id):
        return ProductVariant.objects.filter(
            pk=variant_id, product_id=product_id).select_related('product').first()

    def get(self, request, product_id, variant_id):
        variant = self.get_variant(product_id, variant_id)
        if not variant:
            messages.error(request, 'Variant not found.')
            return redirect('admin-products')
        return self.render_form(request, variant.product, ProductVariantForm(
            product=variant.product, variant=variant, initial={
                'sku': variant.sku, 'size': variant.size, 'color': variant.color,
                'color_hex': variant.color_hex,
                'price': (Decimal(variant.price_minor) / Decimal(100)
                          if variant.price_minor is not None else None),
                'stock_quantity': variant.stock_quantity,
                'is_active': variant.is_active,
            }))

    def post(self, request, product_id, variant_id):
        variant = self.get_variant(product_id, variant_id)
        if not variant:
            messages.error(request, 'Variant not found.')
            return redirect('admin-products')
        form = ProductVariantForm(
            request.POST, product=variant.product, variant=variant)
        if form.is_valid():
            data = form.cleaned_data
            before = {'sku': variant.sku, 'size': variant.size,
                      'color': variant.color, 'color_hex': variant.color_hex,
                      'price_minor': variant.price_minor,
                      'stock_quantity': variant.stock_quantity,
                      'is_active': variant.is_active}
            variant.sku = data['sku']
            variant.size = data['size']
            variant.color = data['color']
            variant.color_hex = data['color_hex']
            variant.price_minor = (int(data['price'] * 100)
                                   if data['price'] is not None else None)
            variant.is_active = data['is_active']
            variant.save()
            stock_delta = data['stock_quantity'] - before['stock_quantity']
            if stock_delta:
                adjust_stock(
                    variant.pk, stock_delta,
                    reason='variant_edit', actor=request.user)
            _audit_catalog('update', variant, metadata={
                'product_id': str(variant.product_id), 'before': before})
            messages.success(request, 'Variant updated.')
            return redirect('admin-product-detail', product_id=variant.product_id)
        return self.render_form(request, variant.product, form)

    def render_form(self, request, product, form):
        return render(request, self.template_name, {
            'form': form,
            'product': product,
            'page_title': 'Edit variant',
            'page_subtitle': f'Update a sellable option for {product.name}.',
            'submit_label': 'Save variant',
        })


@permission_required('variants.delete', 'products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductVariantDeletePageView(View):
    def post(self, request, product_id, variant_id):
        variant = ProductVariant.objects.filter(
            pk=variant_id, product_id=product_id).first()
        if not variant:
            messages.error(request, 'Variant not found.')
            return redirect('admin-products')
        product_id = variant.product_id
        used_in_orders = OrderItem.objects.filter(
            variant_id=variant.id).exists()
        try:
            if not used_in_orders:
                variant.delete()
                _audit_catalog('delete', variant, metadata={
                               'product_id': str(product_id)})
                messages.success(request, 'Variant deleted.')
                return redirect('admin-product-detail', product_id=product_id)
        except ProtectedError:
            pass
        variant.is_active = False
        variant.save(update_fields=['is_active'])
        _audit_catalog(
            'update', variant,
            metadata={'product_id': str(product_id),
                      'is_active': False,
                      'reason': 'used_in_history',
                      'note': 'Deactivated instead of deleted because the '
                              'variant appears in historical orders or '
                              'inventory records.'})
        messages.success(
            request,
            'Variant deactivated because it appears in past orders or has '
            'inventory history. Historical records are preserved.')
        return redirect('admin-product-detail', product_id=product_id)


@permission_required('orders.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class OrderDetailPageView(View):
    template_name = 'admin_ui/order_detail_page.html'

    def get(self, request, order_id):
        order = Order.objects.prefetch_related(
            'items__variant', 'items__product',
            'payment_intents').filter(pk=order_id).first()
        if not order:
            messages.error(request, 'Order not found.')
            return redirect('admin-orders')

        customer = order.customer or {}
        customer_name = (
            customer.get('fullName')
            or customer.get('full_name')
            or customer.get('name')
            or 'Guest customer'
        )
        customer_email = customer.get('email') or (
            order.user.email if order.user else '')
        subtotal = Decimal(order.subtotal_minor) / Decimal(100)
        shipping_total = Decimal(order.shipping_cost_minor) / Decimal(100)
        total = Decimal(order.total_minor) / Decimal(100)

        items = []
        for item in order.items.all():
            items.append({
                'id': item.id,
                'product_name': item.product_name,
                'variant_sku': item.variant_sku,
                'variant_size': item.variant_size,
                'variant_color': item.variant_color,
                'image_url': item.image_url,
                'quantity': item.quantity,
                'line_total_minor': item.line_total_minor,
                'line_total_display': Decimal(item.line_total_minor) / Decimal(100),
            })

        can_approve = (
            order.status == Order.Status.PENDING
            and is_order_approvable(order)
        )

        activity = AuditLog.objects.select_related('actor').filter(
            Q(object_type='order', object_id=str(order.pk))
            | Q(object_type='payment_intent', object_repr=order.order_number)
        )[:40]
        activity = decorate_audit_logs(list(activity))

        receipt = Receipt.objects.select_related('order').filter(
            order=order).first()
        receipt_amount = (
            Decimal(receipt.amount_minor) / Decimal(100)
            if receipt else None
        )

        return render(request, self.template_name, {
            'order': order,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'subtotal': subtotal,
            'shipping_total': shipping_total,
            'total': total,
            'items': items,
            'page_title': f'Order {order.order_number}',
            'page_subtitle': 'Review order details and confirm eligible orders.',
            'can_approve': can_approve,
            'activity_logs': activity,
            'logs': activity,
            'receipt': receipt,
            'receipt_amount': receipt_amount,
            'receipt_download_url': (
                f'/admin/dashboard/orders/{order.pk}/receipt/download/'
                if receipt else ''
            ),
            'receipt_regenerate_url': (
                f'/admin/dashboard/orders/{order.pk}/receipt/regenerate/'
                if receipt else ''
            ),
        })


@permission_required('receipts.view', 'orders.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class OrderReceiptDownloadView(View):
    """Stream the receipt PDF to a staff member (admin download)."""

    def get(self, request, order_id):
        order = Order.objects.filter(pk=order_id).first()
        if not order:
            return HttpResponse('Order not found.', status=404)
        receipt = Receipt.objects.filter(order=order).first()
        if not receipt:
            return HttpResponse('No receipt for this order.', status=404)
        try:
            pdf_bytes = read_pdf_bytes(receipt)
        except Exception:
            logger.exception(
                'Admin receipt download failed for %s.', receipt.receipt_number)
            AuditLogService.log(
                'receipt_downloaded',
                object_type='receipt',
                object_id=receipt.pk,
                object_repr=receipt.receipt_number,
                category='payments',
                result='failure',
                metadata={'reason': 'storage_read_failed',
                          'order_number': order.order_number},
                description=f'Receipt {receipt.receipt_number} download failed.',
            )
            messages.error(request, 'The receipt document is unavailable.')
            return redirect('admin-order-detail', order_id=order.pk)

        AuditLogService.log(
            'receipt_downloaded',
            actor=request.user,
            object_type='receipt',
            object_id=receipt.pk,
            object_repr=receipt.receipt_number,
            category='payments',
            metadata={'order_number': order.order_number},
            description=f'Receipt {receipt.receipt_number} downloaded by staff.',
        )
        from io import BytesIO
        return FileResponse(
            BytesIO(pdf_bytes),
            content_type='application/pdf',
            as_attachment=True,
            filename=f'{receipt.receipt_number}.pdf',
        )


@permission_required('receipts.generate', 'orders.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class OrderReceiptRegenerateView(View):
    """Repair path for a failed/stale receipt, from the admin UI."""

    def post(self, request, order_id):
        order = Order.objects.filter(pk=order_id).first()
        if not order:
            return HttpResponse('Order not found.', status=404)
        receipt = Receipt.objects.filter(order=order).first()
        if not receipt:
            messages.error(
                request, 'No receipt has been issued for this order.')
            return redirect('admin-order-detail', order_id=order.pk)
        try:
            receipt = regenerate_receipt(receipt)
        except Exception:
            logger.exception(
                'Admin receipt regeneration failed for %s.', receipt.receipt_number)
            messages.error(request, 'The receipt could not be regenerated.')
        else:
            messages.success(
                request, f'Receipt {receipt.receipt_number} regenerated.')
        return redirect('admin-order-detail', order_id=order.pk)


@permission_required('products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductDuplicatePageView(View):
    def get(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-dashboard')
        try:
            with transaction.atomic():
                new_product = Product.objects.create(
                    category=product.category,
                    name=f'{product.name} Copy',
                    slug=f'{product.slug}-copy-{uuid.uuid4().hex[:8]}',
                    tagline=product.tagline,
                    description=product.description,
                    details=list(product.details or []),
                    price_minor=product.price_minor,
                    compare_at_price_minor=product.compare_at_price_minor,
                    images=list(product.images or []),
                    status=product.status,
                    is_featured=product.is_featured,
                    is_new_arrival=product.is_new_arrival,
                    is_best_seller=product.is_best_seller,
                )
                for variant in product.variants.all():
                    ProductVariant.objects.create(
                        product=new_product,
                        sku=f'{variant.sku}-copy',
                        size=variant.size,
                        color=variant.color,
                        color_hex=variant.color_hex,
                        price_minor=variant.price_minor,
                        stock_quantity=variant.stock_quantity,
                        is_active=variant.is_active,
                    )
            messages.success(request, 'Product duplicated.')
            _audit_catalog(
                'create', new_product,
                status_code=201,
                metadata={'duplicated_from': str(product.pk),
                          'note': 'duplicate'},
            )
            return redirect(f'/admin/dashboard/products/{new_product.pk}/edit/')
        except IntegrityError:
            messages.error(
                request, 'The duplicated product could not be created.')
            return redirect('admin-dashboard')


@permission_required('products.update')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductArchivePageView(View):
    def get(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        DashboardView.archive_product(product)
        messages.success(request, 'Product archived.')
        return redirect('admin-products')


@permission_required('products.delete')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProductDeletePageView(View):
    def get(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            messages.error(request, 'Product not found.')
            return redirect('admin-products')
        try:
            DashboardView.delete_product(product)
        except IntegrityError:
            messages.error(
                request, 'This product cannot be deleted because it is referenced by an order, cart, or inventory record. Archive it instead.')
        else:
            messages.success(request, 'Product deleted.')
        return redirect('admin-products')


@super_admin_required
@permission_required('staff.create')
class AdminUserInvitePageView(View):
    def get(self, request):
        return redirect('access-staff-create')

    def post(self, request):
        return redirect('access-staff-create')


@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class ProfileSettingsPageView(View):
    template_name = 'admin_ui/profile_settings_page.html'

    def get(self, request):
        return render(request, self.template_name, {
            'page_title': 'My Profile',
            'page_subtitle': 'Admin profile and account settings.',
            'submit_label': 'Save Settings',
            'form': None,
            'user': request.user,
        })


@permission_required('inventory.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class LowStockVariantsPageView(View):
    template_name = 'admin_ui/low_stock_variants_page.html'

    def get(self, request):
        variants = ProductVariant.objects.select_related(
            'product', 'product__category'
        ).filter(stock_quantity__lte=3).order_by(
            'stock_quantity', 'product__name', 'sku')
        return render(request, self.template_name, {
            'variants': variants,
            'low_stock_count': variants.count(),
            'page_title': 'Low stock variants',
            'page_subtitle': 'Review and update variants with 3 or fewer units available.',
            'can_adjust_stock': user_has_permission(request.user, 'inventory.adjust'),
        })

    def post(self, request):
        if not user_has_permission(request.user, 'inventory.adjust'):
            return access_denied_response(request)

        posted_quantities = {
            key[len('quantity_'):]: value
            for key, value in request.POST.items()
            if key.startswith('quantity_')
        }
        if not posted_quantities or len(posted_quantities) > 500:
            messages.error(request, 'Choose at least one variant and enter its new quantity.')
            return redirect('admin-low-stock')

        variants = list(ProductVariant.objects.filter(
            pk__in=posted_quantities).select_related('product'))
        if len(variants) != len(posted_quantities):
            messages.error(request, 'Some variants could not be found. Refresh and try again.')
            return redirect('admin-low-stock')

        desired_quantities = {}
        for variant in variants:
            raw_value = posted_quantities[str(variant.pk)]
            try:
                desired = int(raw_value)
            except (TypeError, ValueError):
                messages.error(request, f'Enter a whole-number quantity for {variant.sku}.')
                return redirect('admin-low-stock')
            if desired < 0 or desired > 1000000:
                messages.error(request, f'Quantity for {variant.sku} must be between 0 and 1,000,000.')
                return redirect('admin-low-stock')
            desired_quantities[variant.pk] = desired

        updated = 0
        with transaction.atomic():
            locked_variants = ProductVariant.objects.select_for_update().filter(
                pk__in=posted_quantities).select_related('product')
            for variant in locked_variants:
                desired = desired_quantities[variant.pk]
                delta = desired - variant.stock_quantity
                if delta:
                    adjust_stock(variant.pk, delta, 'low_stock_page_adjustment', request.user)
                    updated += 1

        if updated:
            messages.success(request, f'Stock updated for {updated} variant{ "s" if updated != 1 else "" }.')
        else:
            messages.info(request, 'No stock changes to save.')
        return redirect('admin-low-stock')


@permission_required('inventory.adjust')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class StockAdjustmentPageView(View):
    template_name = 'admin_ui/stock_form_page.html'

    def get(self, request):
        variant_id = request.GET.get('variant')
        initial = {}
        if variant_id:
            variant = ProductVariant.objects.filter(pk=variant_id).first()
            if variant:
                initial['variant'] = variant
        return self.render_form(request, StockAdjustmentForm(initial=initial))

    def post(self, request):
        form = StockAdjustmentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            adjust_stock(data['variant'].id, data['delta'],
                         data['reason'], request.user)
            messages.success(request, 'Inventory updated.')
            return redirect('admin-inventory')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'Update availability',
            'page_subtitle': 'Keep your stock counts accurate and up to date.',
            'submit_label': 'Update quantity',
        })


class StaffRequiredMixin:
    """Gate a page behind the staff self-service login.

    Anonymous users are redirected to the admin login; authenticated
    non-staff users receive a proper 403 Access Denied message instead of a
    silent redirect, matching the existing self-service admin UX. The backend
    permission is the only authority — nothing here hides data client-side.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), login_url='admin-login')
        if not request.user.is_staff:
            return render(
                request,
                'admin_ui/access_denied.html',
                {
                    'page_title': 'Access Denied',
                    'page_subtitle': "You don't have permission to view system activity.",
                    'admin_page': 'activity',
                    'title': 'Access Denied',
                    'description': "You don't have permission to view system activity.",
                },
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


@super_admin_required
@permission_required('audit_logs.view')
@method_decorator(user_passes_test(is_staff, login_url='admin-login'), name='dispatch')
class AuditLogsPageView(View):
    """Legacy alias of the Activity & Logs overview.

    Kept so existing bookmarks/checks pointing at ``/admin/dashboard/audit-logs/``
    keep working; it renders the same richer overview as ``/activity/``.
    """

    template_name = 'admin_ui/activity_page.html'
    PAGE_SIZE = 25

    def get(self, request):
        return ActivityOverviewPageView.render_activity(
            self, request, template_name=self.template_name)


@super_admin_required
@permission_required('audit_logs.view')
class ActivityOverviewPageView(StaffRequiredMixin, View):
    """Main logging dashboard: summary cards, timeline/table, filters, export."""

    template_name = 'admin_ui/activity_page.html'
    PAGE_SIZE = 25

    def get(self, request):
        return self.render_activity(request)

    def render_activity(self, request, template_name=None):
        filters = normalize_filters(request.GET)
        base_queryset = AuditLog.objects.all()
        queryset = apply_activity_filters(base_queryset, filters)
        summary = compute_summary(queryset)

        paginator = Paginator(queryset, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', '1'))
        logs = decorate_audit_logs(list(page_obj.object_list))

        start_date, end_date, range_label = resolve_date_range(filters)

        range_links = [
            {'key': key, 'label': label,
             'url': build_query(filters, range=key, page=None)}
            for key, label in RANGE_CHOICES if key not in ('custom', 'all')
        ]

        sort_links = [
            {'key': key, 'label': label,
             'url': build_query(filters, sort=key, page=None)}
            for key, label in SORT_CHOICES
        ]
        active_sort_label = dict(SORT_CHOICES).get(filters['sort'], 'Newest')

        active_filters = []
        if filters['q']:
            active_filters.append({'label': f"Search: {filters['q']}",
                                   'remove_url': build_query(filters, q='', page=None)})
        if filters['action']:
            active_filters.append({'label': f"Action: {action_label(filters['action'])}",
                                   'remove_url': build_query(filters, action='', page=None)})
        if filters['category']:
            active_filters.append({'label': f"Category: {category_label(filters['category'])}",
                                   'remove_url': build_query(filters, category='', page=None)})
        if filters['resource']:
            resource_name = RESOURCE_TYPE_LABELS.get(
                filters['resource'], filters['resource'].replace('_', ' ').title())
            active_filters.append({'label': f"Resource: {resource_name}",
                                   'remove_url': build_query(filters, resource='', page=None)})
        if filters['severity']:
            active_filters.append({'label': f"Severity: {severity_meta(filters['severity'])['label']}",
                                   'remove_url': build_query(filters, severity='', page=None)})
        if filters['result']:
            active_filters.append({'label': f"Result: {filters['result'].title()}",
                                   'remove_url': build_query(filters, result='', page=None)})
        if filters['actor']:
            active_filters.append({'label': f"Actor: {filters['actor']}",
                                   'remove_url': build_query(filters, actor='', page=None)})
        if filters['ip']:
            active_filters.append({'label': f"IP: {filters['ip']}",
                                   'remove_url': build_query(filters, ip='', page=None)})
        if filters['request_id']:
            active_filters.append({'label': f"Request: {filters['request_id']}",
                                   'remove_url': build_query(filters, request_id='', page=None)})
        if filters['range'] != 'all' or filters['date_from'] or filters['date_to']:
            active_filters.append({'label': f"Date: {range_label}",
                                   'remove_url': build_query(
                                       filters, range='all', date_from='', date_to='', page=None)})

        clear_url = build_query({'view': filters['view'], 'sort': filters['sort']},
                                range='all')

        user_model = get_user_model()
        actor_options = []
        for admin in user_model.objects.filter(is_staff=True).order_by('username'):
            actor_options.append({
                'value': admin.username,
                'label': admin.get_full_name() or admin.username,
            })

        action_options = [
            {'value': action, 'label': action_label(action)} for action in AUDIT_ACTIONS
        ]
        resource_options = sorted({
            value for value in ActivitySelectors.object_types()
            if value
        })
        category_options = sorted(set(ActivitySelectors.categories()))
        severity_options = [
            {'value': key, 'label': meta['label']}
            for key, meta in sorted(
                SEVERITY_META.items(), key=lambda pair: SEVERITY_ORDER[pair[0]])
        ]
        result_options = [
            {'value': 'success', 'label': 'Success'},
            {'value': 'failure', 'label': 'Failure'},
        ]

        return render(request, template_name or self.template_name, {
            'logs': logs,
            'page_obj': page_obj,
            'summary': summary,
            'range_links': range_links,
            'range_label': range_label,
            'range_key': filters['range'],
            'start_date': start_date,
            'end_date': end_date,
            'sort_links': sort_links,
            'active_sort_label': active_sort_label,
            'sort_key': filters['sort'],
            'view_mode': filters['view'],
            'timeline_url': build_query(filters, view='timeline', page=None),
            'table_url': build_query(filters, view='table', page=None),
            'export_csv_url': build_query(filters, format='csv', view='', sort=''),
            'export_json_url': build_query(filters, format='json', view='', sort=''),
            'active_filters': active_filters,
            'clear_url': clear_url,
            'page_base': build_query(filters, page=''),
            'filters': filters,
            'action_options': action_options,
            'resource_options': resource_options,
            'category_options': category_options,
            'severity_options': severity_options,
            'result_options': result_options,
            'actor_options': actor_options,
            'last_updated': timezone.localtime().strftime('%H:%M:%S'),
            'page_title': 'Activity & Logs',
            'page_subtitle': 'Monitor activity, system events and administrative actions.',
            'admin_page': 'activity',
            'title': 'Activity & Logs',
            'description': 'Monitor activity, system events and administrative actions.',
            'data_loaded': True,
        })


class ActivitySelectors:
    """Read-only distinct values used to populate the activity filter menus."""

    @staticmethod
    def object_types():
        return AuditLog.objects.exclude(object_type='').values_list(
            'object_type', flat=True).distinct()

    @staticmethod
    def categories():
        return AuditLog.objects.exclude(category='').values_list(
            'category', flat=True).distinct()

    @staticmethod
    def actors():
        return get_user_model().objects.filter(is_staff=True).order_by('username')


@super_admin_required
@permission_required('audit_logs.export')
class ActivityExportView(StaffRequiredMixin, View):
    """Export the filtered audit trail as CSV or JSON.

    Derived from the same server-side filter pipeline as the overview so the
    export always matches what the administrator currently sees. Only files
    this endpoint actually supports (csv/json) are offered in the UI.
    """

    FORMATS = ('csv', 'json')
    MAX_ROWS = 10000

    def get(self, request):
        fmt = (request.GET.get('format') or 'csv').lower()
        if fmt not in self.FORMATS:
            return HttpResponseBadRequest('Unsupported export format.')

        filters = normalize_filters(request.GET)
        queryset = apply_activity_filters(
            AuditLog.objects.all(), filters)[:self.MAX_ROWS]
        logs = list(decorate_audit_logs(list(queryset)))
        start, end, range_label = resolve_date_range(filters)

        stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
        filename = f'modeza-activity-{stamp}'

        if fmt == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'time_utc', 'action', 'category', 'severity', 'result',
                'actor', 'actor_email', 'object_type', 'object_id',
                'object_repr', 'description', 'request_id', 'ip_address',
                'path', 'status_code', 'metadata',
            ])
            for log in logs:
                writer.writerow([
                    log.created_at.isoformat(),
                    log.action or '',
                    log.category or '',
                    log.severity or '',
                    log.result or '',
                    log.ui_actor or '',
                    log.actor_email or '',
                    log.object_type or '',
                    log.object_id or '',
                    log.object_repr or '',
                    log.description or '',
                    log.request_id or '',
                    log.ip_address or '',
                    log.path or '',
                    log.status_code or '',
                    json.dumps(log.metadata or {}, default=str),
                ])
            return response

        payload = [{
            'time_utc': log.created_at.isoformat(),
            'action': log.action or '',
            'category': log.category or '',
            'severity': log.severity or '',
            'result': log.result or '',
            'actor': log.ui_actor or '',
            'actor_email': log.actor_email or '',
            'object_type': log.object_type or '',
            'object_id': log.object_id or '',
            'object_repr': log.object_repr or '',
            'description': log.description or '',
            'request_id': log.request_id or '',
            'ip_address': log.ip_address or '',
            'path': log.path or '',
            'status_code': log.status_code,
            'metadata': log.metadata or {},
        } for log in logs]
        response = HttpResponse(
            json.dumps(payload, indent=2, default=str),
            content_type='application/json',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}.json"'
        return response


@super_admin_required
@permission_required('audit_logs.view')
class RequestTracePageView(StaffRequiredMixin, View):
    """Chronological trace of every audit event for a single request ID."""

    template_name = 'admin_ui/request_trace_page.html'

    def get(self, request, request_id):
        request_id = (request_id or '').strip()
        logs = list(AuditLog.objects.select_related('actor').filter(
            request_id=request_id).order_by('created_at', 'id'))
        logs = decorate_audit_logs(logs)
        log_objects = logs

        paths = list(dict.fromkeys(
            log.path for log in log_objects if log.path))

        count_by_action = {}
        for log in log_objects:
            count_by_action[log.ui_action_label] = count_by_action.get(
                log.ui_action_label, 0) + 1

        first_log = log_objects[0] if log_objects else None
        last_log = log_objects[-1] if log_objects else None
        first_time = last_time = None
        duration_ms = None
        if first_log and last_log:
            first_time = timezone.localtime(first_log.created_at)
            last_time = timezone.localtime(last_log.created_at)
            duration_ms = int(
                (last_log.created_at - first_log.created_at).total_seconds() * 1000)

        return render(request, self.template_name, {
            'request_id': request_id,
            'logs': log_objects,
            'paths': paths,
            'count_by_action': count_by_action,
            'total_events': len(log_objects),
            'first_time': first_time,
            'last_time': last_time,
            'duration_ms': duration_ms,
            'page_title': f'Request Trace · {request_id[:24]}',
            'page_subtitle': 'Chronological audit trail for a single request.',
            'admin_page': 'activity',
            'title': 'Request Trace',
            'description': 'Chronological audit trail for a single request.',
        })


@super_admin_required
@permission_required('audit_logs.view')
class SecurityCenterPageView(StaffRequiredMixin, View):
    """Focused view of authentication and security-related audit events."""

    template_name = 'admin_ui/security_page.html'
    LIMIT = 50

    def get(self, request):
        filters = normalize_filters(request.GET)
        base = AuditLog.objects.all()
        secured = apply_activity_filters(base, filters).filter(
            Q(category='security') | Q(action__in=SECURITY_ACTIONS))

        failed_logins = secured.filter(action='login_failed')
        permission_denials = secured.filter(
            action__in=('permission_denied', 'access_denied'))
        suspicious = secured.filter(action='security_event')
        admin_logins = secured.filter(action='login', result='success')
        password_resets = secured.filter(action='password_reset')
        unauthorized = secured.filter(
            severity='critical', result='failure')

        summary = {
            'failed_logins': failed_logins.count(),
            'permission_denials': permission_denials.count(),
            'suspicious': suspicious.count(),
            'admin_logins': admin_logins.count(),
            'password_resets': password_resets.count(),
            'total': secured.count(),
        }

        recent = decorate_audit_logs(
            list(secured.order_by('-created_at')[:self.LIMIT]))
        failed_login_rows = decorate_audit_logs(
            list(failed_logins.order_by('-created_at')[:self.LIMIT]))

        start, end, range_label = resolve_date_range(filters)
        range_links = [
            {'key': key, 'label': label,
             'url': build_query(filters, range=key, page=None)}
            for key, label in RANGE_CHOICES if key not in ('custom', 'all')
        ]

        return render(request, self.template_name, {
            'summary': summary,
            'logs': recent,
            'failed_login_logs': failed_login_rows,
            'range_links': range_links,
            'range_label': range_label,
            'range_key': filters['range'],
            'filters': filters,
            'page_title': 'Security Center',
            'page_subtitle': 'Authentication failures, permission denials and suspicious events.',
            'admin_page': 'security',
            'title': 'Security Center',
            'description': 'Authentication and security events.',
        })


@super_admin_required
@permission_required('audit_logs.view')
class ErrorCenterPageView(StaffRequiredMixin, View):
    """Focused view of failed/high-severity application events."""

    template_name = 'admin_ui/error_center_page.html'
    PAGE_SIZE = 25

    def get(self, request):
        filters = normalize_filters(request.GET)
        errors = apply_activity_filters(AuditLog.objects.all(), filters).filter(
            Q(result='failure') | Q(severity__in=('high', 'critical'))
            | Q(action__in=('server_error', 'payment_failed',
                            'checkout_failed', 'login_failed')))
        total = errors.count()

        paginator = Paginator(errors, self.PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', '1'))
        logs = decorate_audit_logs(list(page_obj.object_list))

        return render(request, self.template_name, {
            'logs': logs,
            'page_obj': page_obj,
            'total_errors': total,
            'page_base': build_query(filters, page=''),
            'filters': filters,
            'range_label': resolve_date_range(filters)[2],
            'action_options': [
                {'value': action, 'label': action_label(action)}
                for action in ('server_error', 'payment_failed',
                               'checkout_failed', 'login_failed',
                               'permission_denied', 'access_denied')
            ],
            'severity_options': [
                {'value': key, 'label': meta['label']}
                for key, meta in SEVERITY_META.items() if key in ('high', 'critical')
            ],
            'page_title': 'Error Center',
            'page_subtitle': 'Failed requests, server errors and high-severity events.',
            'admin_page': 'errors',
            'title': 'Error Center',
            'description': 'Application errors and failures.',
            'data_loaded': True,
        })


@super_admin_required
@permission_required('audit_logs.view')
class SystemHealthPageView(StaffRequiredMixin, View):
    """Honest, read-only system health summary.

    Only checks the backend actually supports are shown. Configuration-only
    checks are labelled ``Configured``/``Unknown`` rather than presenting
    invented latency or uptime numbers.
    """

    template_name = 'admin_ui/system_health_page.html'

    @staticmethod
    def _check_database():
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return {
                'key': 'database', 'name': 'Database',
                'status': 'operational', 'tone': 'success',
                'icon': 'ph-database', 'detail': 'Connected',
            }
        except Exception as exc:  # noqa: BLE001 - surfaced generically
            return {
                'key': 'database', 'name': 'Database',
                'status': 'unavailable', 'tone': 'error',
                'icon': 'ph-database', 'detail': 'Unreachable',
            }

    @staticmethod
    def _check_api():
        return {
            'key': 'api', 'name': 'API & Admin',
            'status': 'operational', 'tone': 'success',
            'icon': 'ph-plugs-connected',
            'detail': 'This page was served successfully.',
        }

    @staticmethod
    def _check_auth():
        configured = bool(
            settings.SUPABASE_JWT_SECRET or settings.SUPABASE_JWT_JWKS_URL)
        return {
            'key': 'auth', 'name': 'Authentication',
            'status': 'operational' if configured else 'unknown',
            'tone': 'success' if configured else 'neutral',
            'icon': 'ph-key',
            'detail': ('Supabase JWT verification configured.'
                       if configured else
                       'Supabase JWT verification is not configured; only the '
                       'Django session login is available.'),
        }

    @staticmethod
    def _check_storage():
        backend = settings.STORAGES['default']['BACKEND']
        if 'Supabase' in backend or supabase_storage_enabled():
            return {
                'key': 'storage', 'name': 'Storage',
                'status': 'operational', 'tone': 'success',
                'icon': 'ph-cloud',
                'detail': 'Supabase Storage configured (uploads are verified at write time).',
            }
        if 'FileSystem' in backend:
            location = settings.MEDIA_ROOT
            writable = False
            try:
                writable = os.access(location, os.W_OK)
            except OSError:
                writable = False
            return {
                'key': 'storage', 'name': 'Storage',
                'status': 'operational' if writable else 'degraded',
                'tone': 'success' if writable else 'warning',
                'icon': 'ph-hard-drives',
                'detail': (f'Local media storage {location} is writable.'
                           if writable else
                           f'Local media storage {location} is not writable.'),
            }
        return {
            'key': 'storage', 'name': 'Storage',
            'status': 'unknown', 'tone': 'neutral', 'icon': 'ph-hard-drives',
            'detail': 'Storage backend could not be determined.',
        }

    @staticmethod
    def _check_payments():
        mpesa = os.environ.get('MPESA_CONSUMER_KEY') \
            and os.environ.get('MPESA_CONSUMER_SECRET')
        webhook = bool(settings.PAYMENT_WEBHOOK_SECRET)
        if webhook and mpesa:
            status, tone = 'operational', 'success'
            detail = 'Payment provider credentials and webhook secret are configured.'
        elif webhook:
            status, tone = 'degraded', 'warning'
            detail = 'Webhook secret configured; MPesa API credentials are missing.'
        else:
            status, tone = 'unknown', 'neutral'
            detail = 'No payment credentials configured; MPesa will not process transactions.'
        return {
            'key': 'payments', 'name': 'Payment Provider',
            'status': status, 'tone': tone, 'icon': 'ph-currency-circle-dollar',
            'detail': detail,
        }

    def get(self, request):
        checks = [
            self._check_database(),
            self._check_api(),
            self._check_auth(),
            self._check_storage(),
            self._check_payments(),
        ]
        return render(request, self.template_name, {
            'checks': checks,
            'note': ('Status on this page reflects live read-only checks. '
                     'Configuration presence is labelled Unknown/Configured — '
                     'no external provider is pinged.'),
            'page_title': 'System Health',
            'page_subtitle': 'Live status of the services Modeza relies on.',
            'admin_page': 'system-health',
            'title': 'System Health',
            'description': 'Service health and configuration status.',
        })


# Anything older than this without a successful run is surfaced as overdue, so
# a sync that broke silently cannot go unnoticed for weeks.
REPLICA_STALE_AFTER = timedelta(hours=36)


@super_admin_required
@permission_required('replica.view')
class ReplicaStatusPageView(StaffRequiredMixin, View):
    """Backup status for the Supabase analytics replica.

    Reports what the replica actually knows -- last run, outcome, per-table
    row counts, image mirror result -- rather than inventing health numbers.
    When Supabase is unreachable the page says so plainly instead of showing
    stale data as if it were current.
    """

    template_name = 'admin_ui/replica_page.html'

    def get(self, request):
        configured = replica_configured()
        run_error = None
        counts_error = None
        try:
            run = latest_run() if configured else None
        except ReplicaStatusUnavailable as exc:
            run = None
            run_error = str(exc)

        live_counts = {}
        if configured:
            try:
                live_counts = current_row_counts()
            except ReplicaStatusUnavailable as exc:
                counts_error = str(exc)

        auto_sync_enabled = getattr(
            settings, 'REPLICA_AUTO_SYNC_ENABLED', False)
        counts_in_sync = bool(live_counts) and all(
            values['source'] == values['replica']
            for values in live_counts.values()
        )

        stale = False
        age_hours = None
        if run and run.get('finished_at'):
            age_hours = round(
                (timezone.now() - run['finished_at']).total_seconds() / 3600, 1
            )
            stale = age_hours > REPLICA_STALE_AFTER.total_seconds() / 3600
            if auto_sync_enabled and counts_in_sync and run['status'] == 'success':
                # No-op polls are deliberately absent from run history. A
                # quiet but reconciled replica should not be called stale.
                stale = False

        counts = []
        for table, values in live_counts.items():
            difference = values['source'] - values['replica']
            counts.append({
                'table': table.replace('_', ' ').title(),
                'source': values['source'],
                'replica': values['replica'],
                'difference': difference,
                'difference_abs': abs(difference),
                'matched': difference == 0,
            })

        return render(request, self.template_name, {
            'page_title': 'Backup to Supabase',
            'page_subtitle': (
                'Analytics replica status, run history and the image mirror.'
            ),
            'admin_page': 'replica',
            'title': 'Backup to Supabase',
            'description': 'Supabase replica status and manual sync.',
            'configured': configured,
            'run': run,
            'run_error': run_error,
            'counts': counts,
            'counts_error': counts_error,
            'counts_checked_at': timezone.now() if counts else None,
            'stale': stale,
            'age_hours': age_hours,
            'stale_after_hours': int(
                REPLICA_STALE_AFTER.total_seconds() / 3600),
            'can_sync': user_has_permission(request.user, 'replica.sync'),
            'backup_bucket': getattr(
                settings, 'REPLICA_BACKUP_BUCKET', ''),
            'cron_configured': bool(
                (getattr(settings, 'REPLICA_SYNC_TOKEN', '') or '').strip()),
            'sync_mode': getattr(settings, 'REPLICA_SYNC_MODE', 'inline'),
            'auto_sync_enabled': auto_sync_enabled,
            'auto_sync_interval_seconds': getattr(
                settings, 'REPLICA_AUTO_SYNC_INTERVAL_SECONDS', 10),
            'pending': pending_request() if configured else None,
        })


@super_admin_required
@permission_required('replica.view')
class ReplicaCountsRefreshView(StaffRequiredMixin, View):
    """Read-only live count endpoint used by the replica status page."""

    def get(self, request):
        if not replica_configured():
            return JsonResponse(
                {'error': 'Supabase replica is not configured.'}, status=503)
        try:
            live_counts = current_row_counts()
        except ReplicaStatusUnavailable as exc:
            return JsonResponse({'error': str(exc)}, status=503)

        rows = []
        for table, values in live_counts.items():
            difference = values['source'] - values['replica']
            rows.append({
                'table': table.replace('_', ' ').title(),
                'source': values['source'],
                'replica': values['replica'],
                'difference': difference,
                'difference_abs': abs(difference),
                'matched': difference == 0,
            })

        response = JsonResponse({
            'counts': rows,
            'checked_at': timezone.localtime().strftime('%d %b %Y, %H:%M:%S'),
        })
        response['Cache-Control'] = 'no-store'
        return response


@super_admin_required
@permission_required('replica.sync')
class ReplicaSyncActionView(StaffRequiredMixin, View):
    """POST-only manual sync trigger.

    Deliberately POST with CSRF: this writes to an external system, and a GET
    link that performs a write can be triggered by a prefetch or a crawler.

    Honours ``REPLICA_SYNC_MODE``. In ``deferred`` the button only queues a run
    and returns immediately, so a long sync cannot outrun the proxy timeout and
    tempt the operator into a retry that starts a second one.
    """

    def get(self, request):
        # Never write on GET -- send the operator to the page instead.
        return redirect('admin-replica')

    def post(self, request):
        if not replica_configured():
            messages.error(
                request,
                'SUPABASE_DB_URL is not set on this deployment, so there is '
                'nowhere to write the replica.'
            )
            return redirect('admin-replica')

        skip_storage = request.POST.get('skip_storage') == 'on'
        raw_limit = (request.POST.get('storage_limit') or '').strip()
        try:
            storage_limit = max(0, int(raw_limit))
        except (TypeError, ValueError):
            storage_limit = None

        deferred = getattr(
            settings, 'REPLICA_SYNC_MODE', 'inline') == 'deferred'

        # Mirror a bounded number of objects first, so a trial run cannot turn
        # into a full copy because one field was left blank.
        if not skip_storage and storage_limit is not None:
            from replica.services.storage_mirror import mirror_bucket
            try:
                info = mirror_bucket(limit=storage_limit)
                messages.info(
                    request,
                    'Mirrored {} object(s) ({} bytes) to the backup '
                    'bucket.'.format(
                        info['objects_copied'], info['bytes_copied']))
            except Exception as exc:  # noqa: BLE001 - reported to the operator
                messages.error(request, f'Storage mirror failed: {exc}')
            skip_storage = True

        if deferred:
            try:
                run_id = queue_replica_sync(triggered_by='manual')
            except ReplicaNotConfigured as exc:
                messages.error(request, str(exc))
                return redirect('admin-replica')
            messages.success(
                request,
                f'Backup queued (run #{run_id}). '
                + (
                    'The automatic sync loop will pick it up shortly.'
                    if getattr(settings, 'REPLICA_AUTO_SYNC_ENABLED', False)
                    else 'The scheduled job will pick it up; watch this page for the result.'
                )
            )
            return redirect('admin-replica')

        try:
            summary = sync_replica(
                triggered_by='manual', include_storage=not skip_storage)
        except ReplicaNotConfigured as exc:
            messages.error(request, str(exc))
            return redirect('admin-replica')
        except ReplicaAlreadyRunning:
            messages.warning(
                request,
                'A replica sync is already running. Wait for it to finish '
                'before starting another.'
            )
            return redirect('admin-replica')
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            logger.exception('Manual replica sync failed.')
            messages.error(request, f'Replica sync failed: {exc}')
            return redirect('admin-replica')

        if summary.get('changes', 0):
            AuditLogService.log(
                'admin_action',
                actor=request.user,
                category='replica',
                result='success',
                metadata={
                    'changes': summary['changes'],
                    'counts': summary.get('counts', {}),
                },
                path=request.path,
                description='Manual replica sync completed with data changes.',
            )
            messages.success(
                request,
                f'Replica sync finished with {summary["changes"]} data '
                'change(s).'
            )
        else:
            messages.info(
                request,
                'Supabase is already up to date. No sync success was logged.'
            )
        return redirect('admin-replica')


class DataResetDisabled(Exception):
    """ENABLE_DATA_RESET is off, so the reset must not exist."""


def _data_reset_enabled(request):
    """Gate the whole reset surface. Returns None when allowed, else a response.

    Every layer checks this -- the views, the nav template and the management
    command -- so removing one environment variable fully disables the feature
    instead of merely hiding the button. Mirrors how EmailSweepView answers 404
    when its token is unset: an unconfigured deployment must not advertise a
    route anyone can knock on.
    """
    if not getattr(settings, 'ENABLE_DATA_RESET', False):
        return HttpResponseNotFound(
            'Data reset is not enabled on this deployment.')
    # Hard superuser gate, not a permission code: codes in the permissions
    # catalog can be granted to other roles, and this one is irreversible.
    if not is_super_admin(request.user):
        return access_denied_response(request)
    return None


class ResetDataMixin:
    """Shared gate for the reset views."""

    def dispatch(self, request, *args, **kwargs):
        denied = _data_reset_enabled(request)
        if denied is not None:
            return denied
        return super().dispatch(request, *args, **kwargs)


class ResetDataPageView(ResetDataMixin, View):
    """Preview what a reset would delete. Read-only, safe to load."""

    template_name = 'admin_ui/reset_data_page.html'

    def get(self, request):
        from maintenance.management.commands.reset_demo_data import (
            DELETION_ORDER,
            PRESERVED,
            build_plan,
        )

        plan = build_plan()
        total = sum(count for _, count in plan)
        return render(request, self.template_name, {
            'page_title': 'Reset demo data',
            'page_subtitle': (
                'One-shot cleanup before real customers arrive.'
            ),
            'admin_page': 'reset-data',
            'title': 'Reset demo data',
            'description': 'Delete all demo and test data.',
            'plan': plan,
            'total': total,
            'has_data': total > 0,
            'preserved': PRESERVED,
            'unknown_models': [
                label for label in DELETION_ORDER
                if build_plan.__module__ and label not in [p[0] for p in plan]
            ],
        })


class ResetDataConfirmView(ResetDataMixin, View):
    """POST-only execution. Requires the operator to type ``WIPE``."""

    template_name = 'admin_ui/reset_data_page.html'

    def get(self, request):
        # Never destroy on GET -- a prefetch must not be able to wipe the store.
        return redirect('admin-reset-data')

    def post(self, request):
        from maintenance.management.commands.reset_demo_data import reset_demo_data

        typed = (request.POST.get('confirm') or '').strip().upper()
        if typed != 'WIPE':
            messages.error(
                request,
                'Confirmation did not match. Nothing was deleted.'
            )
            return redirect('admin-reset-data')

        try:
            summary = reset_demo_data()
        except ProtectedError as exc:
            # Should not happen -- deletion order avoids PROTECT -- but a
            # failure must leave the database untouched, not half-wiped.
            messages.error(
                request,
                f'Reset aborted and rolled back: {exc}'
            )
            return redirect('admin-reset-data')
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            logger.exception('Demo data reset failed.')
            messages.error(request, f'Reset failed and was rolled back: {exc}')
            return redirect('admin-reset-data')

        AuditLogService.log(
            'security_event',
            actor=request.user,
            category='maintenance',
            result='success',
            severity='critical',
            metadata={'deleted': summary['deleted']},
            path=request.path,
            description='Demo data reset executed.',
        )
        messages.success(
            request,
            'Demo data removed. Admin and staff accounts were preserved.'
        )
        return redirect('admin-reset-data')


@permission_required('reports.view')
class AssistantAnalyticsPageView(StaffRequiredMixin, View):
    """AI assistant usage, unanswered questions, tool health.

    Reuses the ``reports.view`` permission — no new RBAC codes. Shows
    aggregates only; raw conversations live in the Django admin.
    """

    template_name = 'admin_ui/assistant_analytics_page.html'

    def get(self, request):
        try:
            days = int(request.GET.get('days', 30))
        except (TypeError, ValueError):
            days = 30
        data = assistant_analytics(days)
        return render(request, self.template_name, {
            'stats': data['totals'],
            'toolUsage': data['toolUsage'],
            'topUnanswered': data['topUnanswered'],
            'daily': data['daily'],
            'days': data['days'],
            'day_choices': (7, 14, 30, 90),
            'max_daily': max((d['questions'] for d in data['daily']), default=0),
            'retention_days': int(getattr(settings, 'ASSISTANT_RETENTION_DAYS', 90)),
            'page_title': 'Assistant Analytics',
            'page_subtitle': 'How customers are using the AI shopping assistant.',
            'admin_page': 'assistant',
            'title': 'Assistant Analytics',
            'description': 'Assistant usage, unanswered questions and tool health.',
        })


@super_admin_required
@permission_required('customers.view')
class CustomerDetailPageView(StaffRequiredMixin, View):
    """Customer profile with the linked audit activity for that account."""

    template_name = 'admin_ui/customer_detail_page.html'

    def get(self, request, customer_id):
        User = get_user_model()
        customer = User.objects.filter(
            pk=customer_id, is_staff=False).first()
        if not customer:
            messages.error(request, 'Customer not found.')
            return redirect('admin-customers')

        orders = Order.objects.filter(user=customer).order_by('-created_at')
        order_count = orders.count()
        total_spent = Decimal(
            orders.exclude(status=Order.Status.CANCELLED).aggregate(
                s=Sum('total_minor'))['s'] or 0) / Decimal(100)

        object_events = AuditLog.objects.select_related('actor').filter(
            Q(object_type__in=('user', 'customer'), object_id=str(customer.pk))
            | Q(actor=customer)
        )
        order_ids = [str(pk) for pk in orders.values_list('pk', flat=True)]
        order_events = AuditLog.objects.select_related('actor').filter(
            object_type='order', object_id__in=order_ids)

        merged = list(object_events) + list(order_events)
        merged.sort(key=lambda log: log.created_at, reverse=True)
        activity = decorate_audit_logs(merged[:60])

        recent_orders = []
        for order in orders[:5]:
            recent_orders.append({
                'id': order.pk,
                'order_number': order.order_number,
                'total': f'KES {Decimal(order.total_minor) / Decimal(100):.2f}',
                'status': order.get_status_display(),
                'payment_status': order.get_payment_status_display(),
                'created_at': order.created_at,
            })

        return render(request, self.template_name, {
            'customer': customer,
            'customer_name': customer.get_full_name() or customer.username,
            'order_count': order_count,
            'total_spent': total_spent,
            'activity_logs': activity,
            'logs': activity,
            'recent_orders': recent_orders,
            'page_title': customer.get_full_name() or customer.username,
            'page_subtitle': 'Customer profile and account activity.',
            'admin_page': 'customers',
            'title': 'Customer Details',
            'description': 'Customer profile and account activity.',
        })
