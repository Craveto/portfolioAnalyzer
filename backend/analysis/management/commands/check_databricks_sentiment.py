from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from api.models import CachedPayload
from portfolio.models import Holding, Portfolio

from analysis.databricks_client import DatabricksQueryError, fetch_one
from analysis.provider import get_portfolio_sentiment, get_stock_insight


class Command(BaseCommand):
    help = "Check Databricks Gold connectivity and verify sentiment cache persistence in the app database."

    def add_arguments(self, parser):
        parser.add_argument("--portfolio-id", type=int, default=None, help="Portfolio id to test against. Defaults to first portfolio.")
        parser.add_argument("--force", action="store_true", help="Force refresh from Databricks (ignore fresh cache).")

    def handle(self, *args, **options):
        provider = (os.getenv("STOCK_INSIGHT_PROVIDER") or "demo").strip().lower()
        if provider != "databricks":
            raise CommandError(
                "STOCK_INSIGHT_PROVIDER is not set to databricks. Update env and rerun."
            )

        portfolio_id = options["portfolio_id"]
        force = options["force"]

        if portfolio_id is None:
            portfolio = Portfolio.objects.order_by("id").first()
        else:
            portfolio = Portfolio.objects.filter(id=portfolio_id).first()

        if not portfolio:
            raise CommandError("No portfolio found. Create at least one portfolio with holdings first.")

        holding = (
            Holding.objects.filter(portfolio=portfolio)
            .select_related("stock")
            .order_by("stock__symbol")
            .first()
        )
        if not holding:
            raise CommandError(f"Portfolio {portfolio.id} has no holdings. Add a stock holding and rerun.")

        symbol = holding.stock.symbol.upper()

        self.stdout.write(
            self.style.SUCCESS(
                f"Using portfolio_id={portfolio.id}, user_id={portfolio.user_id}, symbol={symbol}"
            )
        )
        self.stdout.write(
            f"Database engine={connection.settings_dict.get('ENGINE')}"
        )

        # Lightweight probe first to validate Databricks SQL connectivity.
        try:
            probe = fetch_one("SELECT current_catalog() AS catalog_name, current_schema() AS schema_name")
        except DatabricksQueryError as exc:
            raise CommandError(f"Databricks connectivity failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Databricks probe OK | catalog={probe.get('catalog_name')} schema={probe.get('schema_name')}"
            )
        )

        # Warm portfolio sentiment cache (writes to CachedPayload table in app DB/Supabase DB when configured).
        portfolio_payload = get_portfolio_sentiment(portfolio, force_refresh=force)
        portfolio_cache_key = f"analysis:portfolio_sentiment:{portfolio.id}"
        portfolio_snapshot = CachedPayload.objects.filter(key=portfolio_cache_key).first()

        if not portfolio_snapshot:
            raise CommandError(
                f"Portfolio cache row missing for key {portfolio_cache_key}. Fetch did not persist."
            )

        # Warm stock insight cache.
        stock_payload = get_stock_insight(portfolio, symbol=symbol, force_refresh=force)
        stock_cache_key = f"analysis:stock_insight:{portfolio.id}:{symbol}"
        stock_snapshot = CachedPayload.objects.filter(key=stock_cache_key).first()
        if not stock_snapshot:
            raise CommandError(
                f"Stock cache row missing for key {stock_cache_key}. Fetch did not persist."
            )

        out = {
            "status": "ok",
            "provider": provider,
            "db_engine": connection.settings_dict.get("ENGINE"),
            "portfolio_id": portfolio.id,
            "symbol": symbol,
            "databricks_meta": portfolio_payload.get("meta") or {},
            "portfolio_cache_key": portfolio_cache_key,
            "portfolio_cache_updated_at": portfolio_snapshot.updated_at.isoformat(),
            "stock_cache_key": stock_cache_key,
            "stock_cache_updated_at": stock_snapshot.updated_at.isoformat(),
            "stock_meta": stock_payload.get("meta") or {},
        }
        self.stdout.write(json.dumps(out, indent=2, default=str))

