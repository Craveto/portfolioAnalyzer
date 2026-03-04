from django.urls import path

from .views import ClusterCSVView, ClusterView, PortfolioForecastView, PortfolioPEView

urlpatterns = [
    path("portfolio/<int:portfolio_id>/pe/", PortfolioPEView.as_view(), name="portfolio_pe"),
    path("portfolio/<int:portfolio_id>/forecast/", PortfolioForecastView.as_view(), name="portfolio_forecast"),
    path("cluster/", ClusterView.as_view(), name="cluster"),
    path("cluster/csv/", ClusterCSVView.as_view(), name="cluster_csv"),
]
