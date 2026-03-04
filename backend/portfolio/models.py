from django.conf import settings
from django.db import models


class Sector(models.Model):
    name = models.CharField(max_length=120, unique=True)

    def __str__(self) -> str:
        return self.name


class Stock(models.Model):
    EXCHANGE_CHOICES = [
        ("NSE", "NSE"),
        ("BSE", "BSE"),
    ]

    symbol = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    exchange = models.CharField(max_length=8, choices=EXCHANGE_CHOICES, default="NSE")
    sector = models.ForeignKey(Sector, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.symbol


class Portfolio(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    market = models.CharField(max_length=12, default="IN")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user_id}:{self.name}"


class Holding(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    avg_buy_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("portfolio", "stock")]

    def __str__(self) -> str:
        return f"{self.portfolio_id}:{self.stock_id}"


class Transaction(models.Model):
    SIDE_CHOICES = [
        ("BUY", "BUY"),
        ("SELL", "SELL"),
    ]

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    side = models.CharField(max_length=8, choices=SIDE_CHOICES)
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at", "-id"]

    def __str__(self) -> str:
        return f"{self.portfolio_id}:{self.stock_id}:{self.side}:{self.qty}@{self.price}"
