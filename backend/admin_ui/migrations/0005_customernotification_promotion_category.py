from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_ui', '0004_adminnotification_presented_at_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customernotification',
            name='category',
            field=models.CharField(
                choices=[
                    ('order', 'Order'),
                    ('payment', 'Payment'),
                    ('delivery', 'Delivery'),
                    ('account', 'Account'),
                    ('promotion', 'Promotion'),
                    ('system', 'System'),
                ],
                default='system',
                max_length=20,
            ),
        ),
    ]
