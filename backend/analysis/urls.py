from django.urls import path

from .views import (
    ClusterCSVView,
    ClusterView,
    PortfolioForecastView,
    PortfolioPEView,
    PortfolioSentimentView,
    QuickStockSentimentView,
    StockInsightReportView,
    StockInsightView,
)

urlpatterns = [
    path("portfolio/<int:portfolio_id>/pe/", PortfolioPEView.as_view(), name="portfolio_pe"),
    path("portfolio/<int:portfolio_id>/forecast/", PortfolioForecastView.as_view(), name="portfolio_forecast"),
    path("portfolio/<int:portfolio_id>/sentiment/", PortfolioSentimentView.as_view(), name="portfolio_sentiment"),
    path("portfolio/<int:portfolio_id>/stocks/<str:symbol>/insight/", StockInsightView.as_view(), name="stock_insight"),
    path("portfolio/<int:portfolio_id>/stocks/<str:symbol>/report/", StockInsightReportView.as_view(), name="stock_insight_report"),
    path("portfolio/<int:portfolio_id>/stocks/<str:symbol>/report", StockInsightReportView.as_view(), name="stock_insight_report_no_slash"),
    path("stock/quick-sentiment/", QuickStockSentimentView.as_view(), name="quick_stock_sentiment"),
    path("cluster/", ClusterView.as_view(), name="cluster"),
    path("cluster/csv/", ClusterCSVView.as_view(), name="cluster_csv"),
]
