import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_ui.models import CustomerNotification
from .models import CustomerAddress
from rest_framework import serializers

from .permissions import IsAdmin, IsAuthenticatedSupabaseUser, IsStaffOrAdmin

logger = logging.getLogger("accounts.notifications")


class CustomerAddressSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source='first_name')
    lastName = serializers.CharField(source='last_name')
    addressLine1 = serializers.CharField(source='address_line_1')
    addressLine2 = serializers.CharField(source='address_line_2', required=False, allow_blank=True)
    postalCode = serializers.CharField(source='postal_code', required=False, allow_blank=True)
    isDefault = serializers.BooleanField(source='is_default', required=False)
    phone = serializers.RegexField(regex=r'^[\d\s+().-]{9,25}$')

    class Meta:
        model = CustomerAddress
        fields = ('id', 'label', 'firstName', 'lastName', 'phone', 'addressLine1',
                  'addressLine2', 'county', 'subcounty', 'city', 'postalCode',
                  'country', 'isDefault')
        read_only_fields = ('id',)


class CustomerAddressesView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def get(self, request):
        rows = CustomerAddress.objects.filter(user=request.user)
        return Response(CustomerAddressSerializer(rows, many=True).data)

    def post(self, request):
        serializer = CustomerAddressSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': {'code': 'VALIDATION_ERROR',
                                       'message': 'Address details are invalid.',
                                       'details': serializer.errors}}, status=400)
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            values = dict(serializer.validated_data)
            wants_default = values.pop('is_default', False)
            if wants_default or not CustomerAddress.objects.filter(user=request.user).exists():
                CustomerAddress.objects.filter(user=request.user, is_default=True).update(is_default=False)
                values['is_default'] = True
            address = CustomerAddress.objects.create(user=request.user, **values)
        return Response(CustomerAddressSerializer(address).data, status=status.HTTP_201_CREATED)


class CustomerAddressDetailView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def patch(self, request, address_id):
        address = CustomerAddress.objects.filter(user=request.user, pk=address_id).first()
        if not address:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Address was not found.', 'details': {}}}, status=404)
        serializer = CustomerAddressSerializer(address, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'error': {'code': 'VALIDATION_ERROR',
                                       'message': 'Address details are invalid.',
                                       'details': serializer.errors}}, status=400)
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            if serializer.validated_data.get('is_default'):
                CustomerAddress.objects.filter(user=request.user, is_default=True).exclude(pk=address.pk).update(is_default=False)
            updated = serializer.save()
        return Response(CustomerAddressSerializer(updated).data)

    def delete(self, request, address_id):
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            address = CustomerAddress.objects.filter(user=request.user, pk=address_id).first()
            if not address:
                return Response({'error': {'code': 'NOT_FOUND', 'message': 'Address was not found.', 'details': {}}}, status=404)
            was_default = address.is_default
            address.delete()
            if was_default:
                next_address = CustomerAddress.objects.filter(user=request.user).order_by('created_at').first()
                if next_address:
                    next_address.is_default = True
                    next_address.save(update_fields=['is_default', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def get(self, request):
        return Response({
            'id': request.user.username.removeprefix('supabase_'),
            'email': request.user.email,
            'role': getattr(request.user, 'supabase_role', 'customer'),
        })


class AdminAccessView(APIView):
    permission_classes = [IsStaffOrAdmin]

    def get(self, request):
        return Response({'status': 'ok', 'role': request.user.supabase_role})


class OwnerAccessView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response({'status': 'ok', 'role': request.user.supabase_role})


class CustomerNotificationsView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def get(self, request):
        queryset = CustomerNotification.objects.filter(user=request.user)
        total = queryset.count()
        unread_count = queryset.filter(is_read=False).count()
        limit = min(int(request.query_params.get('limit', 20)), 500)
        notifications = queryset.order_by('-created_at')[:limit]
        return Response({
            'count': total,
            'unread_count': unread_count,
            'results': [{
                'id': str(notification.id),
                'category': notification.category,
                'title': notification.title,
                'message': notification.message,
                'link': notification.link,
                'isRead': notification.is_read,
                'presented': notification.presented_at is not None,
                'createdAt': notification.created_at.isoformat(),
            } for notification in notifications],
        })


class MarkCustomerNotificationsPresentedView(APIView):
    """Atomically claim popup presentation for a set of notification IDs.

    Only the caller that wins the compare-and-set is told the IDs were
    actually ``presented_at``; concurrent clients (other tabs, polls racing)
    receive an empty ``presented`` list for IDs already surfaced, so a single
    notification can never be popped more than once regardless of polling,
    refresh, or page remount.
    """

    permission_classes = [IsAuthenticatedSupabaseUser]

    def post(self, request):
        ids = request.data.get('ids') or []
        if not isinstance(ids, list):
            return Response(
                {'ok': False, 'error': 'ids must be a list'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cleaned = []
        for raw in ids[:100]:
            try:
                cleaned.append(raw if isinstance(raw, str) else str(raw))
            except (TypeError, ValueError):
                continue
        if not cleaned:
            return Response({'ok': True, 'presented': []})

        try:
            with transaction.atomic():
                rows = CustomerNotification.objects.select_for_update().filter(
                    user=request.user,
                    pk__in=cleaned,
                )
                won = []
                for notification in rows:
                    if notification.presented_at is None and not notification.is_read:
                        notification.presented_at = timezone.now()
                        notification.save(update_fields=['presented_at'])
                        won.append(notification.pk)
        except Exception:
            logger.warning(
                'notification_present_failed recipient=%s ids=%d',
                request.user.pk, len(cleaned), exc_info=True)
            return Response(
                {'ok': False, 'presented': []},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        logger.debug(
            'notification_presented recipient=%s total=%d won=%d',
            request.user.pk, len(cleaned), len(won))
        return Response({
            'ok': True,
            'presented': [str(nid) for nid in won],
        })


class MarkAllCustomerNotificationsReadView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def post(self, request):
        updated = CustomerNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(is_read=True)
        return Response({'ok': True, 'unread_count': 0, 'updated': updated})


class MarkCustomerNotificationReadView(APIView):
    permission_classes = [IsAuthenticatedSupabaseUser]

    def post(self, request, notification_id):
        notification = CustomerNotification.objects.filter(
            user=request.user,
            pk=notification_id,
        ).first()
        if not notification:
            return Response({'ok': False}, status=404)

        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        unread_count = CustomerNotification.objects.filter(
            user=request.user, is_read=False).count()
        return Response({'ok': True, 'unread_count': unread_count})
