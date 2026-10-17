import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0010_product_fit_and_reviews'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BulkUploadSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('filename', models.CharField(max_length=255)),
                ('file_size', models.PositiveBigIntegerField()),
                ('chunk_size', models.PositiveIntegerField()),
                ('chunk_count', models.PositiveIntegerField()),
                ('import_status', models.CharField(default='DRAFT', max_length=10)),
                ('received_chunks', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('owner', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
