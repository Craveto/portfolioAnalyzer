from django.core.management.base import BaseCommand

from portfolio.models import Sector, Stock


class Command(BaseCommand):
    help = "Seed a small set of Indian stocks for Day-1 demo."

    def handle(self, *args, **options):
        it, _ = Sector.objects.get_or_create(name="IT")
        fin, _ = Sector.objects.get_or_create(name="Financials")
        cons, _ = Sector.objects.get_or_create(name="Consumer")
        energy, _ = Sector.objects.get_or_create(name="Energy")

        stocks = [
            ("RELIANCE.NS", "Reliance Industries", "NSE", energy),
            ("TCS.NS", "Tata Consultancy Services", "NSE", it),
            ("INFY.NS", "Infosys", "NSE", it),
            ("HDFCBANK.NS", "HDFC Bank", "NSE", fin),
            ("ICICIBANK.NS", "ICICI Bank", "NSE", fin),
            ("SBIN.NS", "State Bank of India", "NSE", fin),
            ("ITC.NS", "ITC", "NSE", cons),
        ]

        created = 0
        for symbol, name, exchange, sector in stocks:
            _, was_created = Stock.objects.get_or_create(
                symbol=symbol,
                defaults={"name": name, "exchange": exchange, "sector": sector},
            )
            created += 1 if was_created else 0

        self.stdout.write(self.style.SUCCESS(f"Seeded stocks. Newly created: {created}"))
