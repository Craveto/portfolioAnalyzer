from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    REDIRECT_CHOICES = [
        ("dashboard", "Dashboard"),
        ("account", "Account"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    full_name = models.CharField(max_length=150, blank=True, default="")
    bio = models.CharField(max_length=280, blank=True, default="")
    default_redirect = models.CharField(max_length=24, choices=REDIRECT_CHOICES, default="dashboard")
    default_portfolio = models.ForeignKey(
        "portfolio.Portfolio",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_profiles",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"profile:{self.user_id}"
