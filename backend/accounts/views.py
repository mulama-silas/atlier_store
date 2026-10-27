import logging
import time
import uuid

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_ui.models import CustomerNotification
from .models import CustomerAddress, CustomerProfile

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


class CustomerProfileUpdateSerializer(serializers.Serializer):
    fullName = serializers.CharField(max_length=150, trim_whitespace=True)
    phone = serializers.RegexField(regex=r'^[\d\s+().-]{9,25}$')

    def validate_fullName(self, value):
        normalized = ' '.join(value.split())
        if not normalized:
            raise serializers.ValidationError('Enter your full name.')
        return normalized


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
        return Response(self.profile_data(request.user))

    def patch(self, request):
        serializer = CustomerProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        full_name = serializer.validated_data['fullName']
        phone = serializer.validated_data['phone'].strip()
        name_parts = full_name.split(' ', 1)

        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(
                pk=request.user.pk)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            user.save(update_fields=['first_name', 'last_name'])
            CustomerProfile.objects.update_or_create(
                user=user,
                defaults={'phone': phone},
            )

        return Response(self.profile_data(user))

    @staticmethod
    def profile_data(user):
        full_name = ' '.join(user.get_full_name().split())
        profile = CustomerProfile.objects.filter(user=user).first()
        phone = profile.phone if profile else ''
        if not phone:
            default_address = CustomerAddress.objects.filter(
                user=user, is_default=True).first()
            phone = default_address.phone if default_address else ''
        return {
            'id': user.username.removeprefix('supabase_'),
            'email': user.email,
            'role': getattr(user, 'supabase_role', 'customer'),
            'fullName': full_name,
            'phone': phone,
            'isComplete': bool(full_name and phone),
        }


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


# ---------------------------------------------------------------------------
# Local storefront authentication (development only)
#
# These endpoints back VITE_AUTH_MODE=django: registration, sign-in and
# password changes against the local database instead of Supabase Auth, so the
# storefront can be exercised end to end with nothing but
# `python manage.py runserver`. Each one answers 404 whenever
# LOCAL_AUTH_ENABLED is off (which is every production deploy), so this adds
# no authentication surface in production.
# ---------------------------------------------------------------------------


def _local_auth_error(code, message, details=None,
                      http_status=status.HTTP_400_BAD_REQUEST):
    """Project-wide error envelope, matching api_exception_handler's shape."""
    error = {'code': code, 'message': message}
    if details is not None:
        error['details'] = details
    return Response({'error': error}, status=http_status)


def _local_auth_disabled_response():
    return _local_auth_error(
        'NOT_FOUND',
        'Local authentication is disabled on this server.',
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _local_session_user(user):
    """Supabase-shaped user payload, so the storefront needs no special casing."""
    profile = CustomerProfile.objects.filter(user=user).first()
    phone = profile.phone if profile else ''
    full_name = ' '.join(user.get_full_name().split())
    email = user.email or ''
    return {
        'id': user.username.removeprefix('supabase_'),
        'email': email,
        'aud': 'authenticated',
        'role': getattr(user, 'supabase_role', 'customer'),
        'user_metadata': {
            'full_name': full_name,
            'phone': phone,
            'email': email,
        },
        'app_metadata': {'provider': 'local', 'role': 'customer'},
        'identities': [{
            'provider': 'local',
            'identity_data': {
                'email': email,
                'full_name': full_name,
                'phone': phone,
            },
        }],
        'created_at': user.date_joined.isoformat() if user.date_joined else None,
    }


def _issue_local_session(user):
    """Mint the bearer token the storefront sends as `Bearer local.<jwt>`."""
    issued_at = int(time.time())
    ttl = settings.LOCAL_AUTH_TOKEN_TTL
    claims = {
        'sub': str(user.pk),
        'email': user.email or '',
        'iat': issued_at,
        'exp': issued_at + ttl,
        'iss': settings.LOCAL_AUTH_ISSUER,
        'aud': settings.LOCAL_AUTH_AUDIENCE,
    }
    token = jwt.encode(claims, settings.LOCAL_AUTH_SECRET, algorithm='HS256')
    return Response({
        'access_token': f'{settings.LOCAL_AUTH_TOKEN_PREFIX}{token}',
        'token_type': 'bearer',
        'expires_in': ttl,
        'expires_at': issued_at + ttl,
        'user': _local_session_user(user),
    })


class LocalRegisterView(APIView):
    """Create a customer in the local `auth_user` table and sign them in.

    Unlike the Supabase flow there is no email-verification step: the account
    has to be usable from a browser tab that has no mail relay behind it.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.LOCAL_AUTH_ENABLED:
            return _local_auth_disabled_response()

        email = str(request.data.get('email') or '').strip().lower()
        password = str(request.data.get('password') or '')
        full_name = ' '.join(str(request.data.get('fullName') or '').split())
        phone = str(request.data.get('phone') or '').strip()

        local_part, separator, domain = email.partition('@')
        details = {}
        if not separator or not local_part or '.' not in domain:
            details['email'] = ['Enter a valid email address.']
        if len(password) < 8:
            details['password'] = ['Password must be at least 8 characters long.']
        if not full_name:
            details['fullName'] = ['Enter your name.']
        if not phone:
            details['phone'] = ['Enter your phone number.']
        if details:
            return _local_auth_error(
                'VALIDATION_ERROR', 'Your account details are invalid.', details)

        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            return _local_auth_error(
                'EMAIL_TAKEN', 'An account with that email already exists.')

        with transaction.atomic():
            user = User.objects.create_user(
                username=f'local_{uuid.uuid4().hex[:16]}',
                email=email,
                password=password,
            )
            name_parts = full_name.split(' ', 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            user.save(update_fields=['first_name', 'last_name'])
            CustomerProfile.objects.update_or_create(
                user=user, defaults={'phone': phone[:25]})

        from audit.services import AuditLogService

        AuditLogService.log(
            'signup',
            actor=user,
            category='account',
            object_type='customer',
            object_id=user.pk,
            object_repr=user.email or user.username,
            result='success',
            description='Account created through local development auth.',
        )
        return _issue_local_session(user)


class LocalLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.LOCAL_AUTH_ENABLED:
            return _local_auth_disabled_response()

        email = str(request.data.get('email') or '').strip().lower()
        password = str(request.data.get('password') or '')

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        # check_password runs for unknown emails too, so a missing account and
        # a wrong password take comparable time to reject.
        credentials_valid = user is not None and user.check_password(password)
        if not credentials_valid or (user is not None and not user.is_active):
            return _local_auth_error(
                'INVALID_CREDENTIALS',
                'That email and password combination is not correct.',
                http_status=status.HTTP_401_UNAUTHORIZED,
            )
        return _issue_local_session(user)


class LocalPasswordView(APIView):
    """Change the signed-in local user's password.

    The storefront already re-authenticated with the current password through
    its sign-in call before offering this form, so the bearer token is enough.
    """

    permission_classes = [IsAuthenticatedSupabaseUser]

    def post(self, request):
        if not settings.LOCAL_AUTH_ENABLED:
            return _local_auth_disabled_response()

        new_password = str(request.data.get('password') or '')
        if len(new_password) < 8:
            return _local_auth_error(
                'VALIDATION_ERROR',
                'Choose a password with at least 8 characters.',
                {'password': ['Password must be at least 8 characters long.']})

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        return Response({'ok': True, 'user': _local_session_user(request.user)})


class LocalLogoutView(APIView):
    """Local tokens are stateless; the client simply discards its copy."""

    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.LOCAL_AUTH_ENABLED:
            return _local_auth_disabled_response()
        return Response({'ok': True})
