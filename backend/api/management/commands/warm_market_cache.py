from django.core.management.base import BaseCommand

from api.views import MarketSummaryView, warm_market_summary_cache


class Command(BaseCommand):
    help = "Warm and persist the landing market summary cache."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Refresh even if cache is still fresh.")

    def handle(self, *args, **options):
        payload = warm_market_summary_cache(
            cache_key=MarketSummaryView.CACHE_KEY,
            top_universe=MarketSummaryView.TOP_UNIVERSE,
            force=bool(options.get("force")),
            fresh_seconds=MarketSummaryView.FRESH_SECONDS,
        )
        meta = payload.get("meta", {})
        self.stdout.write(
            self.style.SUCCESS(
                f"Market cache ready | source={meta.get('source', 'unknown')} | updated_at={meta.get('updated_at', '-')}"
            )
        )
