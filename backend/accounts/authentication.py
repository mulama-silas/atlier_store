import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from audit.services import AuditLogService


class SupabaseJWTAuthentication(BaseAuthentication):
    keyword = b'bearer'
    jwks_client = None

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            raise AuthenticationFailed(
                'Authorization header must use Bearer authentication.')
        return self.authenticate_token(parts[1].decode('utf-8'))

    def authenticate_token(self, token):
        if not settings.SUPABASE_JWT_SECRET and not settings.SUPABASE_JWT_JWKS_URL:
            raise AuthenticationFailed(
                'Supabase JWT verification is not configured.')
        options = {'require': ['sub', 'exp', 'iat']}
        if settings.SUPABASE_JWT_ISSUER:
            issuer = settings.SUPABASE_JWT_ISSUER
        try:
            token_header = jwt.get_unverified_header(token)
            algorithm = token_header.get('alg')
            if algorithm == 'ES256':
                if not settings.SUPABASE_JWT_JWKS_URL:
                    raise AuthenticationFailed(
                        'Supabase JWKS verification is not configured.')
                if self.jwks_client is None:
                    self.jwks_client = jwt.PyJWKClient(
                        settings.SUPABASE_JWT_JWKS_URL)
                signing_key = self.jwks_client.get_signing_key_from_jwt(
                    token).key
                decode_kwargs = {
                    'key': signing_key,
                    'algorithms': ['ES256'],
                    'audience': settings.SUPABASE_JWT_AUDIENCE,
                    'options': options,
                }
            else:
                if not settings.SUPABASE_JWT_SECRET:
                    raise AuthenticationFailed(
                        'Supabase legacy JWT verification is not configured.')
                decode_kwargs = {
                    'key': settings.SUPABASE_JWT_SECRET,
                    'algorithms': ['HS256'],
                    'audience': settings.SUPABASE_JWT_AUDIENCE,
                    'options': options,
                }
            if settings.SUPABASE_JWT_ISSUER:
                decode_kwargs['issuer'] = issuer
            claims = jwt.decode(token, **decode_kwargs)
        except (jwt.PyJWTError, AuthenticationFailed) as exc:
            raise AuthenticationFailed(
                'Invalid or expired Supabase access token.') from exc

        subject = claims.get('sub')
        if not subject:
            raise AuthenticationFailed('Supabase token has no subject.')
        role = self.get_role(claims)
        user, created = self.get_or_create_user(subject, claims)
        user.supabase_role = role
        user.supabase_claims = claims
        self.sync_local_role(user, role)
        self.sync_local_name(user, claims)
        if created and role == 'customer':
            self.send_welcome(user, claims)
        return user, token

    @staticmethod
    def send_welcome(user, claims):
        """Queue the one-off welcome email for a brand-new customer account.

        Only account creation triggers this, so it cannot repeat in normal
        traffic; ``welcome:user:{pk}`` makes it exactly-once anyway should the
        creation ever be replayed. Staff/admin sign-ups are skipped.
        """
        from emails.services import queue_email

        metadata = (claims.get('user_metadata')
                    or claims.get('raw_user_meta_data') or {})
        display = str(metadata.get('full_name') or metadata.get('name')
                      or '').strip()
        if not display:
            display = (user.get_full_name() or '').strip()
        email = str(user.email or claims.get('email') or '').strip()
        if '@' not in email:
            return

        origin = getattr(settings, 'FRONTEND_ORIGIN', 'http://localhost:3000')
        store = getattr(settings, 'STORE_NAME', 'MODEZA Boutique')
        queue_email(
            email_type='welcome',
            subject=f'Welcome to {store}',
            body_text=(
                f'Hi {display or "there"},\n\n'
                f'Your {store} account is ready. You can track orders, '
                'keep your details on file and check out faster next time.\n\n'
                f'Start shopping: {origin}/\n\n'
                f'{store}\n{getattr(settings, "STORE_ADDRESS", "")}'
            ),
            recipient_email=email,
            recipient_name=display,
            related_user=user,
            idempotency_key=f'welcome:user:{user.pk}',
            notification={
                'category': 'account',
                'title': f'Welcome to {store}',
                'message': 'Your account is ready.',
                'link': '/account/',
                'event_key': f'customer-welcome:{user.pk}',
            },
        )

    @staticmethod
    def get_role(claims):
        app_metadata = claims.get('app_metadata') or {}
        role = app_metadata.get('role', 'customer')
        return role if role in {'customer', 'staff', 'admin'} else 'customer'

    @staticmethod
    def sync_local_role(user, role):
        should_be_staff = role in {'staff', 'admin'}
        updates = []
        if user.is_staff != should_be_staff:
            user.is_staff = should_be_staff
            updates.append('is_staff')
        if user.is_superuser and role != 'admin':
            user.is_superuser = False
            updates.append('is_superuser')
        if updates:
            user.save(update_fields=updates)

    @staticmethod
    def sync_local_name(user, claims):
        metadata = claims.get('user_metadata') or claims.get(
            'raw_user_meta_data') or {}
        full_name = str(metadata.get('full_name')
                        or metadata.get('name') or '').strip()
        if not full_name:
            return

        name_parts = full_name.split()
        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:])
        updates = []
        if user.first_name != first_name:
            user.first_name = first_name
            updates.append('first_name')
        if user.last_name != last_name:
            user.last_name = last_name
            updates.append('last_name')
        if updates:
            user.save(update_fields=updates)

    @staticmethod
    def get_or_create_user(subject, claims):
        User = get_user_model()
        username = f'supabase_{subject}'
        email = claims.get('email', '')
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_active': True},
        )
        if created:
            audit_log = AuditLogService.log(
                'signup',
                actor=user,
                category='account',
                object_type='customer',
                object_id=user.pk,
                object_repr=user.email or user.username,
                result='success',
                description=f'Account created for a new Supabase identity.',
            )
            # Provisioning the local customer is the first server-verifiable
            # confirmation that a Supabase signup became an active account.
            # Emit here so email-confirmation signups (which have no session
            # during the browser's signup request) still reach the admin bell.
            if audit_log is not None:
                from admin_ui.services import AdminNotificationService

                AdminNotificationService.notify_for_audit(
                    audit_log,
                    message=f'New customer account created: {user.email or user.username}.',
                    link=f'/admin/dashboard/customers/{user.pk}/',
                    event_key=f'customer-registered:{user.pk}',
                )
        if not created and email and user.email != email:
            user.email = email
            user.save(update_fields=['email'])
        return user, created
