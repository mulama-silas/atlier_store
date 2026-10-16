import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name='CustomerAddress',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('label', models.CharField(blank=True, max_length=80)),
                ('first_name', models.CharField(max_length=80)),
                ('last_name', models.CharField(max_length=80)),
                ('phone', models.CharField(max_length=25)),
                ('address_line_1', models.CharField(max_length=200)),
                ('address_line_2', models.CharField(blank=True, max_length=200)),
                ('county', models.CharField(max_length=100)),
                ('subcounty', models.CharField(blank=True, max_length=100)),
                ('city', models.CharField(max_length=100)),
                ('postal_code', models.CharField(blank=True, max_length=20)),
                ('country', models.CharField(default='Kenya', max_length=80)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_addresses', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-is_default', 'created_at')},
        ),
        migrations.AddConstraint(
            model_name='customeraddress',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('user',), name='one_default_address_per_customer'),
        ),
    ]
