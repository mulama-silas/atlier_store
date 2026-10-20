from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('receipts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='receipt',
            name='receipt_number',
            field=models.CharField(max_length=17, unique=True),
        ),
    ]
