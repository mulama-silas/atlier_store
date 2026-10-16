from datetime import datetime, timedelta, timezone

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from admin_ui.models import CustomerNotification
from accounts.models import CustomerProfile


@override_settings(
    SUPABASE_JWT_SECRET='test-secret-that-is-at-least-32-bytes',
    SUPABASE_JWT_ISSUER='',
)
class SupabaseAuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def token(self, role='customer', subject='user-123', full_name=None, phone=None,
              user_role=None):
        now = datetime.now(timezone.utc)
        claims = {
            'sub': subject,
            'email': f'{subject}@example.com',
            'aud': 'authenticated',
            'iat': now,
            'exp': now + timedelta(minutes=5),
            'app_metadata': {'role': role},
        }
        metadata = {}
        if full_name:
            metadata['full_name'] = full_name
        if phone:
            metadata['phone'] = phone
        if user_role:
            metadata['role'] = user_role
        if metadata:
            claims['user_metadata'] = metadata
        return jwt.encode(
            claims, 'test-secret-that-is-at-least-32-bytes', algorithm='HS256')

    def auth(self, role='customer', subject='user-123'):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token(role, subject)}')

    def test_valid_token_resolves_current_user_and_role(self):
        self.auth('customer')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'customer')

    def test_customer_is_denied_staff_route(self):
        self.auth('customer')

        response = self.client.get('/api/admin/access')

        self.assertEqual(response.status_code, 403)

    def test_staff_can_access_staff_route_but_not_admin_route(self):
        self.auth('staff')

        self.assertEqual(self.client.get('/api/admin/access').status_code, 200)
        self.assertEqual(self.client.get(
            '/api/admin/owner-access').status_code, 403)

    def test_admin_can_access_both_protected_routes(self):
        self.auth('admin')

        self.assertEqual(self.client.get('/api/admin/access').status_code, 200)
        self.assertEqual(self.client.get(
            '/api/admin/owner-access').status_code, 200)

    def test_staff_role_syncs_to_local_user_without_customer_status(self):
        self.auth('staff', subject='staff-user')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        user = response.wsgi_request.user
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_customer_role_is_not_local_staff(self):
        self.auth('customer', subject='customer-user')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_staff)

    def test_user_editable_metadata_cannot_grant_staff_role(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token(subject="role-escalation", user_role="admin")}')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'customer')
        self.assertFalse(response.wsgi_request.user.is_staff)

    def test_supabase_full_name_syncs_to_local_user(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token(subject="named-user", full_name="Ada Lovelace")}')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        user = response.wsgi_request.user
        self.assertEqual(user.get_full_name(), 'Ada Lovelace')

    def test_profile_get_returns_incomplete_for_google_user_without_phone(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token(subject="google-user", full_name="Ada Lovelace")}')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fullName'], 'Ada Lovelace')
        self.assertEqual(response.json()['phone'], '')
        self.assertFalse(response.json()['isComplete'])

    def test_profile_patch_persists_and_get_returns_updated_values(self):
        self.auth(subject='profile-user')

        response = self.client.patch('/api/auth/me', {
            'fullName': '  Ada   Lovelace  ', 'phone': '+254 700 123 456',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fullName'], 'Ada Lovelace')
        self.assertEqual(response.json()['phone'], '+254 700 123 456')
        self.assertTrue(response.json()['isComplete'])
        user = get_user_model().objects.get(username='supabase_profile-user')
        self.assertEqual(user.get_full_name(), 'Ada Lovelace')
        self.assertEqual(CustomerProfile.objects.get(user=user).phone, '+254 700 123 456')

        refreshed = self.client.get('/api/auth/me')
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()['fullName'], 'Ada Lovelace')
        self.assertTrue(refreshed.json()['isComplete'])

    def test_profile_update_is_user_scoped_and_does_not_trust_client_user_id(self):
        User = get_user_model()
        other_user = User.objects.create_user(
            username='supabase-other-user', password='test-password',
            first_name='Other', last_name='Customer')
        CustomerProfile.objects.create(user=other_user, phone='+254 711 111 111')
        self.auth(subject='profile-user')

        response = self.client.patch('/api/auth/me', {
            'user_id': other_user.pk,
            'fullName': 'Current Customer', 'phone': '+254 700 222 222',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        other_user.refresh_from_db()
        self.assertEqual(other_user.get_full_name(), 'Other Customer')
        self.assertEqual(CustomerProfile.objects.get(user=other_user).phone, '+254 711 111 111')

    def test_invalid_profile_update_does_not_change_saved_values(self):
        self.auth(subject='profile-user')
        self.client.patch('/api/auth/me', {
            'fullName': 'Saved Customer', 'phone': '+254 700 222 222',
        }, format='json')

        response = self.client.patch('/api/auth/me', {
            'fullName': ' ', 'phone': 'not a phone',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        user = get_user_model().objects.get(username='supabase_profile-user')
        self.assertEqual(user.get_full_name(), 'Saved Customer')
        self.assertEqual(CustomerProfile.objects.get(user=user).phone, '+254 700 222 222')

    def test_profile_patch_requires_authentication(self):
        response = self.client.patch('/api/auth/me', {
            'fullName': 'Ada Lovelace', 'phone': '+254 700 123 456',
        }, format='json')

        self.assertEqual(response.status_code, 401)

    def test_backend_profile_wins_over_stale_google_metadata_on_later_requests(self):
        self.auth(subject='google-user')
        self.client.patch('/api/auth/me', {
            'fullName': 'Updated Name', 'phone': '+254 700 123 456',
        }, format='json')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token(subject="google-user", full_name="Old Google Name", phone="+254 700 000 000")}')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fullName'], 'Updated Name')
        self.assertEqual(response.json()['phone'], '+254 700 123 456')
        self.assertEqual(get_user_model().objects.filter(username='supabase_google-user').count(), 1)
        self.assertEqual(CustomerProfile.objects.filter(user__username='supabase_google-user').count(), 1)

    def test_invalid_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')

        response = self.client.get('/api/auth/me')

        self.assertEqual(response.status_code, 401)


class CustomerNotificationTests(TestCase):
    """Presentation-aware customer notification lifecycle.

    Covers the regression: an unread notification must stay unread, but its
    popup must be surfaced exactly once — even across refresh/remount/polling.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='notify-customer', password='test-password',
            email='notify@example.com')

    def test_customer_notifications_report_presented_flag(self):
        notification = CustomerNotification.objects.create(
            user=self.user, category='order', title='Order placed',
            message='Your order AT-C-PRESENTED-001 has been placed.',
            is_read=False)
        self.client.force_login(self.user)

        response = self.client.get('/api/notifications')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 1)
        result = response.json()['results'][0]
        self.assertEqual(result['id'], str(notification.pk))
        self.assertIs(result['presented'], False)
        self.assertFalse(result['isRead'])

    def test_customer_presented_is_idempotent_and_keeps_unread(self):
        notification = CustomerNotification.objects.create(
            user=self.user, category='order', title='Order placed',
            message='Your order AT-C-PRESENT-001 has been placed.',
            is_read=False)
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/notifications/presented/',
            {'ids': [str(notification.pk)]}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [str(notification.pk)])

        fresh_response = self.client.get('/api/notifications')
        self.assertEqual(fresh_response.json()['unread_count'], 1)
        self.assertTrue(fresh_response.json()['results'][0]['presented'])
        self.assertFalse(fresh_response.json()['results'][0]['isRead'])

        # A second claim (another tab, refresh, poll) is a no-op.
        response = self.client.post(
            '/api/notifications/presented/',
            {'ids': [str(notification.pk)]}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [])

    def test_customer_presented_is_user_isolated(self):
        other = get_user_model().objects.create_user(
            username='notify-other', password='test-password',
            email='other@example.com')
        notification = CustomerNotification.objects.create(
            user=other, category='order', title='Other order',
            message='Not for the first customer.', is_read=False)
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/notifications/presented/',
            {'ids': [str(notification.pk)]}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['presented'], [])
        notification.refresh_from_db()
        self.assertIsNone(notification.presented_at)

    def test_customer_cannot_fetch_other_users_notifications(self):
        other = get_user_model().objects.create_user(
            username='notify-other-2', password='test-password',
            email='other2@example.com')
        CustomerNotification.objects.create(
            user=other, category='order', title='Hidden order',
            message='Secrets.', is_read=False)
        self.client.force_login(self.user)

        response = self.client.get('/api/notifications')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)
        self.assertEqual(response.json()['results'], [])

    def test_customer_presented_requires_authentication(self):
        anonymous = APIClient()

        response = anonymous.post(
            '/api/notifications/presented/',
            {'ids': []}, format='json')

        self.assertEqual(response.status_code, 401)

    def test_customer_mark_read_is_idempotent(self):
        notification = CustomerNotification.objects.create(
            user=self.user, category='order', title='Order placed',
            message='Your order AT-C-READ-001 has been placed.',
            is_read=False)
        self.client.force_login(self.user)

        first = self.client.post(
            f'/api/notifications/{notification.pk}/read/', format='json')
        second = self.client.post(
            f'/api/notifications/{notification.pk}/read/', format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertEqual(
            CustomerNotification.objects.filter(
                user=self.user, is_read=False).count(), 0)

    def test_customer_mark_all_read_clears_unread_even_when_presented(self):
        CustomerNotification.objects.create(
            user=self.user, category='order', title='A',
            message='A message', is_read=False, presented_at=django_timezone.now())
        CustomerNotification.objects.create(
            user=self.user, category='payment', title='B',
            message='B message', is_read=False)
        self.client.force_login(self.user)

        response = self.client.post(
            '/api/notifications/read-all/', format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 0)
        self.assertEqual(
            CustomerNotification.objects.filter(
                user=self.user, is_read=False).count(), 0)
