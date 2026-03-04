from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portfolio", "0002_transaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(blank=True, default="", max_length=150)),
                ("bio", models.CharField(blank=True, default="", max_length=280)),
                ("default_redirect", models.CharField(choices=[("dashboard", "Dashboard"), ("account", "Account")], default="dashboard", max_length=24)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "default_portfolio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="default_for_profiles",
                        to="portfolio.portfolio",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]

