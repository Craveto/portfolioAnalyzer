from django.contrib import admin

from .models import Holding, Portfolio, Sector, Stock, Transaction


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "exchange", "sector", "is_active")
    list_filter = ("exchange", "sector", "is_active")
    search_fields = ("symbol", "name")


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "market", "created_at")
    list_filter = ("market",)
    search_fields = ("name", "user__username")


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("id", "portfolio", "stock", "qty", "avg_buy_price", "updated_at")
    search_fields = ("portfolio__name", "stock__symbol")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "portfolio", "stock", "side", "qty", "price", "realized_pnl", "executed_at")
    list_filter = ("side", "executed_at")
    search_fields = ("portfolio__name", "stock__symbol")
