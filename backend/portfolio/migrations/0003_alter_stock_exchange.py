from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0002_transaction"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stock",
            name="exchange",
            field=models.CharField(
                choices=[
                    ("NSE", "NSE"),
                    ("BSE", "BSE"),
                    ("NASDAQ", "NASDAQ"),
                    ("NYSE", "NYSE"),
                    ("US", "US"),
                ],
                default="US",
                max_length=8,
            ),
        ),
    ]
