from __future__ import annotations

from django.core.management.base import BaseCommand

from portfolio.models import Holding, Portfolio

from analysis.provider import get_portfolio_sentiment, get_stock_insight


class Command(BaseCommand):
    help = "Warm Databricks-backed sentiment cache for portfolios and holdings."

    def add_arguments(self, parser):
        parser.add_argument("--portfolio-id", type=int, default=None, help="Warm only one portfolio id.")
        parser.add_argument("--max-stocks-per-portfolio", type=int, default=3, help="How many holdings per portfolio to warm.")

    def handle(self, *args, **options):
        portfolio_id = options["portfolio_id"]
        max_stocks = max(1, int(options["max_stocks_per_portfolio"] or 3))

        if portfolio_id:
            portfolios = Portfolio.objects.filter(id=portfolio_id).order_by("id")
        else:
            portfolios = Portfolio.objects.order_by("id")

        warmed_portfolios = 0
        warmed_stock_entries = 0

        for portfolio in portfolios:
            try:
                get_portfolio_sentiment(portfolio, force_refresh=True)
                warmed_portfolios += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Portfolio {portfolio.id} warm failed: {exc}"))
                continue

            holdings = (
                Holding.objects.filter(portfolio=portfolio)
                .select_related("stock")
                .order_by("stock__symbol")[:max_stocks]
            )
            for h in holdings:
                try:
                    get_stock_insight(portfolio, h.stock.symbol, force_refresh=True)
                    warmed_stock_entries += 1
                except Exception as exc:
                    self.stdout.write(
                        self.style.WARNING(f"Stock warm failed | portfolio={portfolio.id} symbol={h.stock.symbol}: {exc}")
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Sentiment warm complete | portfolios={warmed_portfolios} stock_entries={warmed_stock_entries}"
            )
        )

