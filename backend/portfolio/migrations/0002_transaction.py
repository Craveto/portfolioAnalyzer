from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("portfolio", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Transaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("side", models.CharField(choices=[("BUY", "BUY"), ("SELL", "SELL")], max_length=8)),
                ("qty", models.DecimalField(decimal_places=4, max_digits=18)),
                ("price", models.DecimalField(decimal_places=4, max_digits=18)),
                ("realized_pnl", models.DecimalField(decimal_places=4, default=0, max_digits=18)),
                ("executed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "portfolio",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="portfolio.portfolio"),
                ),
                (
                    "stock",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="portfolio.stock"),
                ),
            ],
            options={
                "ordering": ["-executed_at", "-id"],
            },
        ),
    ]

