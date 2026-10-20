import uuid

from django.db import models

from orders.models import Order


class Receipt(models.Model):
    """One official receipt per paid order.

    Created automatically when an order's payment succeeds (M-Pesa callback or
    customer confirm). The :attr:`snapshot` freezes the customer, items and
    totals at generation time so a receipt is never rewritten by later order
    changes — it is the legal proof of sale, not a live view.
    """

    class Status(models.TextChoices):
        GENERATED = 'generated', 'Generated'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name='receipt')
    receipt_number = models.CharField(max_length=17, unique=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.GENERATED)
    # Immutable copy of the billed entity, bought items and totals.
    snapshot = models.JSONField(default=dict)
    # Storage key + renderable URL for the generated PDF (default_storage).
    pdf_key = models.CharField(max_length=500, blank=True)
    pdf_url = models.URLField(blank=True)
    payload_size = models.PositiveIntegerField(default=0)
    amount_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default='KES')
    # M-Pesa traceability.
    gateway_reference = models.CharField(max_length=80, blank=True)
    checkout_request_id = models.CharField(max_length=100, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_attempts = models.PositiveIntegerField(default=0)
    email_error = models.CharField(max_length=300, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=('order', 'created_at')),
        ]

    def __str__(self):
        return self.receipt_number


class ReceiptSequence(models.Model):
    """Legacy per-year sequence retained for existing database records."""

    year = models.PositiveIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.year}: {self.last_number}'
