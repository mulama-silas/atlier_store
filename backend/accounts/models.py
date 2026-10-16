import uuid

from django.conf import settings
from django.db import models


class CustomerAddress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='customer_addresses')
    label = models.CharField(max_length=80, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=25)
    address_line_1 = models.CharField(max_length=200)
    address_line_2 = models.CharField(max_length=200, blank=True)
    county = models.CharField(max_length=100)
    subcounty = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, default='Kenya')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-is_default', 'created_at')
        constraints = [
            models.UniqueConstraint(
                fields=('user',), condition=models.Q(is_default=True),
                name='one_default_address_per_customer'),
        ]

    def __str__(self):
        return f'{self.label or "Address"} for {self.user_id}'
