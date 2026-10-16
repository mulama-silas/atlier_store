import uuid

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0009_alter_productimage_image_url'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='product', name='material',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='product', name='care_instructions',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='product', name='fit_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='product', name='model_size',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='product', name='garment_measurements',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='ProductReview',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('rating', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('title', models.CharField(max_length=120)),
                ('body', models.TextField(max_length=2000)),
                ('is_approved', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to='catalog.product')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_reviews', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at',)},
        ),
        migrations.AddConstraint(
            model_name='productreview',
            constraint=models.UniqueConstraint(fields=('product', 'user'), name='unique_product_review_per_user'),
        ),
        migrations.AddConstraint(
            model_name='productreview',
            constraint=models.CheckConstraint(condition=models.Q(('rating__gte', 1), ('rating__lte', 5)), name='product_review_rating_1_to_5'),
        ),
    ]
