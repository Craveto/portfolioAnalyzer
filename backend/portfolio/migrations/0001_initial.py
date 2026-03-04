# Generated manually for Day-1 scaffold (equivalent to makemigrations).
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Sector",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="Portfolio",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("market", models.CharField(default="IN", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Stock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("exchange", models.CharField(choices=[("NSE", "NSE"), ("BSE", "BSE")], default="NSE", max_length=8)),
                ("is_active", models.BooleanField(default=True)),
                ("sector", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="portfolio.sector")),
            ],
        ),
        migrations.CreateModel(
            name="Holding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("qty", models.DecimalField(decimal_places=4, max_digits=18)),
                ("avg_buy_price", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("portfolio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="portfolio.portfolio")),
                ("stock", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="portfolio.stock")),
            ],
            options={
                "unique_together": {("portfolio", "stock")},
            },
        ),
    ]
