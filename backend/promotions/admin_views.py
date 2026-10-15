"""Staff promotion administration (RBAC via AdminPermission)."""
import logging
from copy import deepcopy

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from access_control.drf_permissions import AdminPermission
from admin_api.views import AdminAPIView
from audit.services import AuditLogService
from orders.models import Order

from .models import Promotion, PromotionRedemption, normalize_coupon_code
from .serializers import PromotionWriteSerializer, apply_write_data, promotion_to_dict
from .notifications import notify_promotion_customers

logger = logging.getLogger('promotions.admin_views')


def _audit(action, promo, metadata=None, result='success', status_code=None):
    return AuditLogService.log(
        action, object_type='promotion', object_id=promo.pk, object_repr=promo.name,
        category='orders', result=result, metadata=metadata or {},
        status_code=status_code, description=f'{action}: promotion {promo.name}.')


def _unique_code_ok(normalized, exclude_pk=None):
    if not normalized:
        return True
    qs = Promotion.objects.filter(coupon_code_normalized=normalized).exclude(
        status__in=[Promotion.Status.DISABLED, Promotion.Status.EXPIRED])
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


class AdminPromotionListCreateView(AdminAPIView):
    required_permissions = ['promotions.view']

    def get(self, request):
        qs = Promotion.objects.all().order_by('-priority', '-created_at')
        status_filter = (request.query_params.get('status') or '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        results = [promotion_to_dict(p) for p in qs[:200]]
        counts = {
            'active': Promotion.objects.filter(status='active').count(),
            'scheduled': Promotion.objects.filter(status='scheduled').count(),
            'expired': Promotion.objects.filter(status='expired').count(),
            'disabled': Promotion.objects.filter(status='disabled').count(),
        }
        return Response({'counts': counts, 'results': results})

    def post(self, request):
        # Enforce create permission explicitly (AdminPermission already checks view-level).
        from access_control.services import user_has_permission
        if not (user_has_permission(request.user, 'promotions.create') or user_has_permission(request.user, 'promotions.update')):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'Missing promotions.create.',
                                       'details': {}}}, status=403)
        serializer = PromotionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized = normalize_coupon_code(serializer.validated_data.get('coupon_code') or '')
        if not _unique_code_ok(normalized):
            return Response({'error': {'code': 'DUPLICATE_CODE',
                                       'message': 'An active promotion already uses this code.',
                                       'details': {}}}, status=400)
        with transaction.atomic():
            promo = Promotion()
            apply_write_data(promo, serializer.validated_data, user=request.user)
            if promo.status == Promotion.Status.ACTIVE:
                notify_promotion_customers(promo)
        _audit('promotion_created', promo, status_code=201)
        return Response(promotion_to_dict(promo), status=201)


class AdminPromotionDetailView(AdminAPIView):
    required_permissions = ['promotions.view']

    def get(self, request, promo_id):
        promo = get_object_or_404(Promotion, pk=promo_id)
        return Response(_detail(promo))

    def patch(self, request, promo_id):
        from access_control.services import user_has_permission
        if not user_has_permission(request.user, 'promotions.update'):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'Missing promotions.update.',
                                       'details': {}}}, status=403)
        promo = get_object_or_404(Promotion, pk=promo_id)
        old_code = promo.coupon_code_normalized
        # Merge existing values with the patch for full validation.
        current = _to_input(promo)
        merged = dict(current)
        merged.update(request.data or {})
        serializer = PromotionWriteSerializer(data=merged)
        serializer.is_valid(raise_exception=True)
        normalized = normalize_coupon_code(serializer.validated_data.get('coupon_code') or '')
        if not _unique_code_ok(normalized, exclude_pk=promo.pk):
            return Response({'error': {'code': 'DUPLICATE_CODE',
                                       'message': 'An active promotion already uses this code.',
                                       'details': {}}}, status=400)
        with transaction.atomic():
            previous_status = promo.status
            apply_write_data(promo, serializer.validated_data, user=request.user)
            if (
                previous_status != Promotion.Status.ACTIVE
                and promo.status == Promotion.Status.ACTIVE
            ):
                notify_promotion_customers(promo)
        if old_code != promo.coupon_code_normalized:
            _audit('promotion_code_changed', promo, metadata={'from': old_code, 'to': promo.coupon_code_normalized})
        _audit('promotion_updated', promo)
        return Response(_detail(promo))

    def delete(self, request, promo_id):
        from access_control.services import user_has_permission
        if not user_has_permission(request.user, 'promotions.delete'):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'Missing promotions.delete.',
                                       'details': {}}}, status=403)
        promo = get_object_or_404(Promotion, pk=promo_id)
        name = promo.name
        promo.delete()
        AuditLogService.log('promotion_deleted', object_type='promotion', object_id=promo_id,
                            object_repr=name, category='orders',
                            description=f'promotion_deleted: promotion {name}.')
        return Response({'ok': True})


class AdminPromotionActionView(AdminAPIView):
    required_permissions = ['promotions.update']

    def post(self, request, promo_id, action):
        promo = get_object_or_404(Promotion, pk=promo_id)
        if action == 'activate':
            if not promo.ends_at:
                return Response({
                    'error': {
                        'code': 'END_DATE_REQUIRED',
                        'message': 'Set an end date before publishing this promotion.',
                        'details': {},
                    },
                }, status=400)
            was_active = promo.status == Promotion.Status.ACTIVE
            with transaction.atomic():
                promo.status = Promotion.Status.ACTIVE
                promo.save(update_fields=['status', 'updated_at'])
                if not was_active:
                    notify_promotion_customers(promo)
            _audit('promotion_activated', promo)
        elif action == 'deactivate':
            promo.status = Promotion.Status.DISABLED
            promo.save(update_fields=['status', 'updated_at'])
            _audit('promotion_deactivated', promo)
        elif action == 'duplicate':
            with transaction.atomic():
                clone = deepcopy(promo)
                clone.pk = None
                clone.name = f'{promo.name} (copy)'
                clone.coupon_code = ''
                clone.coupon_code_normalized = ''
                clone.status = Promotion.Status.DRAFT
                clone.save()
                for link in promo.promo_products.all():
                    promo.promo_products.model.objects.create(promotion=clone, product=link.product)
                for link in promo.promo_categories.all():
                    promo.promo_categories.model.objects.create(promotion=clone, category=link.category)
                for link in promo.promo_variants.all():
                    promo.promo_variants.model.objects.create(promotion=clone, variant=link.variant)
            _audit('promotion_created', clone, metadata={'duplicated_from': str(promo.pk)})
            return Response(_detail(clone), status=201)
        else:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Unknown action.',
                                       'details': {}}}, status=404)
        return Response(_detail(promo))


class AdminPromotionAnalyticsView(AdminAPIView):
    required_permissions = ['promotions.view']

    def get(self, request, promo_id):
        promo = get_object_or_404(Promotion, pk=promo_id)
        redemptions = PromotionRedemption.objects.filter(promotion=promo, voided=False).select_related('order')
        orders = [r.order for r in redemptions if r.order_id]
        revenue = sum(o.total_minor for o in orders)
        discount = sum(r.discount_minor + r.shipping_discount_minor for r in redemptions)
        count = redemptions.count()
        return Response({
            'id': str(promo.pk), 'name': promo.name, 'code': promo.coupon_code,
            'redemptions': count,
            'revenue': revenue / 100,
            'discountGiven': discount / 100,
            'averageOrder': (revenue / count / 100) if count else 0,
            'usageLimit': promo.usage_limit,
            'remaining': (promo.usage_limit - count) if promo.usage_limit is not None else None,
            'usagePercent': round(count / promo.usage_limit * 100, 1) if promo.usage_limit else 0,
        })


class AdminPromotionPreviewView(AdminAPIView):
    required_permissions = ['promotions.view']

    def post(self, request, promo_id):
        promo = get_object_or_404(Promotion, pk=promo_id)
        example = float(request.data.get('exampleCart') or 10000)
        example_minor = int(round(example * 100))
        discount = 0
        if promo.promotion_type == 'percentage':
            from decimal import Decimal
            discount = int(Decimal(example_minor) * Decimal(promo.discount_percent or 0) / Decimal(100))
            if promo.maximum_discount_minor is not None:
                discount = min(discount, promo.maximum_discount_minor)
        elif promo.promotion_type == 'fixed':
            discount = min(promo.discount_amount_minor or 0, example_minor)
        return Response({
            'name': promo.coupon_code or promo.name, 'type': promo.promotion_type,
            'exampleCart': example, 'discount': discount / 100,
            'final': (example_minor - discount) / 100,
        })


def _detail(promo):
    data = promotion_to_dict(promo)
    data.update({
        'productIds': [str(link.product_id) for link in promo.promo_products.all()],
        'categoryIds': [str(link.category_id) for link in promo.promo_categories.all()],
        'variantIds': [str(link.variant_id) for link in promo.promo_variants.all()],
        'customerIds': [link.user_id for link in promo.promo_customers.all()],
    })
    return data


def _to_input(promo):
    return {
        'name': promo.name, 'description': promo.description,
        'promotion_type': promo.promotion_type, 'status': promo.status,
        'discount_percent': float(promo.discount_percent or 0),
        'discount_amount': (promo.discount_amount_minor or 0) / 100,
        'maximum_discount': (promo.maximum_discount_minor / 100) if promo.maximum_discount_minor is not None else None,
        'minimum_order_value': (promo.minimum_order_value_minor or 0) / 100,
        'minimum_quantity': promo.minimum_quantity,
        'qualifying_quantity': promo.qualifying_quantity,
        'reward_quantity': promo.reward_quantity,
        'reward_discount_percent': float(promo.reward_discount_percent or 0),
        'max_redemptions_per_order': promo.max_redemptions_per_order,
        'coupon_code': promo.coupon_code or '', 'is_automatic': promo.is_automatic,
        'starts_at': promo.starts_at.isoformat() if promo.starts_at else None,
        'ends_at': promo.ends_at.isoformat() if promo.ends_at else None,
        'usage_limit': promo.usage_limit, 'usage_limit_per_customer': promo.usage_limit_per_customer,
        'priority': promo.priority, 'stackable': promo.stackable,
        'eligible_all': promo.eligible_all, 'sale_only': promo.sale_only, 'new_only': promo.new_only,
        'customer_scope': promo.customer_scope,
        'product_ids': [str(link.product_id) for link in promo.promo_products.all()],
        'category_ids': [str(link.category_id) for link in promo.promo_categories.all()],
        'variant_ids': [str(link.variant_id) for link in promo.promo_variants.all()],
        'customer_ids': [link.user_id for link in promo.promo_customers.all()],
    }
