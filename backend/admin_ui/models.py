import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models


class AdminNotification(models.Model):
    class Category(models.TextChoices):
        ORDER = 'order', 'Order'
        PAYMENT = 'payment', 'Payment'
        INVENTORY = 'inventory', 'Inventory'
        SYSTEM = 'system', 'System'
        CUSTOMER = 'customer', 'Customer'
        SECURITY = 'security', 'Security'

    class Severity(models.TextChoices):
        INFO = 'info', 'Info'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admin_notifications',
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.SYSTEM,
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True, default='')
    event_key = models.CharField(max_length=200, blank=True, db_index=True)
    # Correlation with the audit trail. ``event_type`` mirrors the canonical
    # audit action (order_created, payment_failed, ...) so the admin UI can
    # group and filter notifications without re-deriving it from the title.
    event_type = models.CharField(max_length=40, blank=True, default='', db_index=True)
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    audit_log = models.ForeignKey(
        'audit.AuditLog',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admin_notifications',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    resource_type = models.CharField(max_length=40, blank=True, default='')
    resource_id = models.CharField(max_length=100, blank=True, default='')
    request_id = models.CharField(max_length=80, blank=True, default='', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # Timestamp of the first time the notification was surfaced (popup/toast)
    # to ``recipient``. Independent from read state: a surfaced notification
    # stays unread until the admin explicitly reads it, but it is never
    # re-surfaced once ``presented_at`` is set.
    presented_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=('recipient', 'is_read', '-created_at')),
            models.Index(fields=('recipient', 'category', '-created_at')),
        ]

    def __str__(self):
        return f'{self.title} ({self.category})'


class CustomerNotification(models.Model):
    class Category(models.TextChoices):
        ORDER = 'order', 'Order'
        PAYMENT = 'payment', 'Payment'
        DELIVERY = 'delivery', 'Delivery'
        ACCOUNT = 'account', 'Account'
        PROMOTION = 'promotion', 'Promotion'
        SYSTEM = 'system', 'System'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_notifications',
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.SYSTEM,
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True, default='')
    event_key = models.CharField(max_length=200, blank=True, db_index=True)
    event_type = models.CharField(max_length=40, blank=True, default='')
    severity = models.CharField(
        max_length=10,
        default='info',
    )
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    # Timestamp of the first time the notification was surfaced (popup/toast)
    # to ``user``. Independent from read state; see AdminNotification.
    presented_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.category})'


def notify_staff(category, title, message, link='', event_key='', recipient=None,
                 event_type='', severity='info', audit_log=None, actor=None,
                 resource_type='', resource_id='', request_id='', metadata=None):
    staff_users = get_user_model().objects.filter(is_staff=True)
    if recipient is not None:
        staff_users = staff_users.filter(pk=recipient.pk)

    notifications = []
    for staff_user in staff_users:
        dedupe_key = event_key or f'{category}:{staff_user.pk}:{title}:{message}'
        if dedupe_key and AdminNotification.objects.filter(
            recipient=staff_user,
            event_key=dedupe_key,
        ).exists():
            continue
        notifications.append(
            AdminNotification.objects.create(
                recipient=staff_user,
                category=category,
                title=title,
                message=message,
                link=link,
                event_key=dedupe_key,
                event_type=event_type,
                severity=severity,
                audit_log=audit_log,
                actor=actor,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                metadata=metadata or {},
            )
        )
    return notifications


def notify_customer(user, category, title, message, link='', event_key='',
                    recipient=None, event_type='', severity='info',
                    audit_log=None, metadata=None):
    if user is None:
        return None
    target_user = user if recipient is None else recipient
    dedupe_key = event_key or f'{category}:{target_user.pk}:{title}:{message}'
    if target_user and CustomerNotification.objects.filter(
        user=target_user,
        event_key=dedupe_key,
    ).exists():
        return None
    return CustomerNotification.objects.create(
        user=target_user,
        category=category,
        title=title,
        message=message,
        link=link,
        event_key=dedupe_key,
        event_type=event_type,
        severity=severity,
        metadata=metadata or {},
    )


def notify_customers(users, category, title, message, link='', event_key=''):
    queryset = users if hasattr(users, 'all') else [users]
    notifications = []
    for user in queryset:
        notification = notify_customer(
            user, category, title, message, link=link, event_key=event_key)
        if notification is not None:
            notifications.append(notification)
    return notifications
