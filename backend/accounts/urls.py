from django.urls import path

from .views import (
    AdminAccessView,
    CustomerNotificationsView,
    CurrentUserView,
    CustomerAddressesView,
    CustomerAddressDetailView,
    LocalLoginView,
    LocalLogoutView,
    LocalPasswordView,
    LocalRegisterView,
    MarkAllCustomerNotificationsReadView,
    MarkCustomerNotificationsPresentedView,
    MarkCustomerNotificationReadView,
    OwnerAccessView,
)


urlpatterns = [
    path('auth/me', CurrentUserView.as_view(), name='current-user'),
    # Development-only auth (404 in production, see LOCAL_AUTH_ENABLED).
    path('auth/register', LocalRegisterView.as_view(), name='local-register'),
    path('auth/login', LocalLoginView.as_view(), name='local-login'),
    path('auth/password', LocalPasswordView.as_view(), name='local-password'),
    path('auth/logout', LocalLogoutView.as_view(), name='local-logout'),
    path('admin/access', AdminAccessView.as_view(), name='admin-access'),
    path('admin/owner-access', OwnerAccessView.as_view(), name='owner-access'),
    path('notifications', CustomerNotificationsView.as_view(),
         name='customer-notifications'),
    path('addresses', CustomerAddressesView.as_view(), name='customer-addresses'),
    path('addresses/<uuid:address_id>', CustomerAddressDetailView.as_view(),
         name='customer-address-detail'),
    path('notifications/presented/',
         MarkCustomerNotificationsPresentedView.as_view(),
         name='customer-notifications-presented'),
    path('notifications/read-all/',
         MarkAllCustomerNotificationsReadView.as_view(),
         name='customer-notifications-read-all'),
    path('notifications/<uuid:notification_id>/read/',
         MarkCustomerNotificationReadView.as_view(), name='customer-notification-read'),
]
