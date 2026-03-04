from django.conf import settings
from django.db import models


class WatchlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stock = models.ForeignKey("portfolio.Stock", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "stock")]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"watch:{self.user_id}:{self.stock_id}"


class PriceAlert(models.Model):
    DIRECTION_CHOICES = [
        ("ABOVE", "ABOVE"),
        ("BELOW", "BELOW"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stock = models.ForeignKey("portfolio.Stock", on_delete=models.CASCADE)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    target_price = models.DecimalField(max_digits=18, decimal_places=4)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    triggered_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"alert:{self.user_id}:{self.stock_id}:{self.direction}:{self.target_price}"
