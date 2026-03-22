# Stock Insight Module Blueprint

## Best-fit plan for this project

This repository currently uses:

- Backend: Django + DRF
- Frontend: React + Vite
- Hosted DB: Supabase Postgres
- Live market data today: `yfinance`

Because Databricks is not wired into the repo yet, the best implementation path is:

1. Build the UI contract and backend sentiment flow now inside Django.
2. Keep the response shape aligned to the future Databricks Gold tables.
3. Replace the internal data source later with Databricks SQL queries without rewriting the frontend.

That is what the current implementation does.

## Final target architecture

### Supabase

Use Supabase for:

- users
- portfolios
- holdings
- watchlists
- report history
- file metadata

### Databricks

Use Databricks for:

- Bronze ingestion from Supabase holdings
- raw stock news ingestion
- raw market context ingestion
- Silver cleaning and deduplication
- Silver sentiment scoring
- Gold stock insight outputs
- Gold portfolio summary outputs
- Gold report-ready datasets

### Django backend

Use Django for:

- auth and authorization
- querying Databricks SQL warehouse
- shaping UI responses
- report download endpoints
- on-demand LLM explanation later

### React frontend

Use React for:

- stock insight cards
- portfolio summary cards
- top news display
- risk badges
- report actions

## Recommended medallion tables

### Bronze

- `bronze_portfolio_snapshot`
- `bronze_news_raw`
- `bronze_market_data_raw`

### Silver

- `silver_portfolio_clean`
- `silver_news_clean`
- `silver_news_scored`
- `silver_market_data_clean`

### Gold

- `gold_stock_insight_current`
- `gold_stock_news_view`
- `gold_portfolio_summary`
- `gold_stock_report_dataset`

## Databricks job order

1. `ingest_supabase_portfolio`
2. `build_active_ticker_list`
3. `fetch_news_for_tickers`
4. `fetch_market_context`
5. `clean_portfolio_data`
6. `clean_news_data`
7. `score_news_with_finbert`
8. `aggregate_stock_gold_tables`
9. `aggregate_portfolio_gold_tables`
10. `build_report_dataset`

## API contract to preserve

The current Django implementation already follows this Gold-style shape:

- `GET /api/analysis/portfolio/{portfolioId}/sentiment/`
- `GET /api/analysis/portfolio/{portfolioId}/stocks/{symbol}/insight/`
- `GET /api/analysis/portfolio/{portfolioId}/stocks/{symbol}/report/?format=md`
- `GET /api/analysis/portfolio/{portfolioId}/stocks/{symbol}/report/?format=csv`

When Databricks is connected, only the internal implementation should change.
The frontend should continue using the same endpoints.

## Backend provider switch

The backend should keep one provider switch:

- `STOCK_INSIGHT_PROVIDER=demo`
- `STOCK_INSIGHT_PROVIDER=databricks`

Today the repo is running in `demo` mode.
Later, only the provider implementation should change, not the frontend contract.

## Current working demo behavior

Today the repo does this:

- pulls holdings from the current portfolio in Django
- fetches market context from `yfinance`
- fetches ticker news from `yfinance` when available
- applies a heuristic sentiment layer for demo readiness
- returns stock insight cards and downloadable reports

This is the fastest path for your teacher demo.

## Phase 2 implementation note

For this project, the correct ingestion source is not the frontend and not raw CSV files.
It is the Supabase Postgres database already used by Django.

That means Step 2 should read from the current Django tables:

- `portfolio_portfolio`
- `portfolio_holding`
- `portfolio_stock`
- `portfolio_sector`
- `auth_user`

The repo now includes a starter Databricks notebook template for this step:

- [01_ingest_supabase_portfolio.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/01_ingest_supabase_portfolio.py)

And the field mapping document here:

- [supabase_to_bronze_mapping.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/supabase_to_bronze_mapping.md)

## Phase 3 implementation note

The next correct data-platform step after active ticker generation is raw news ingestion.

The repo now includes:

- [04_fetch_news_for_tickers.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/04_fetch_news_for_tickers.py)
- [news_ingestion_provider.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/news_ingestion_provider.md)

This step should stay simple:

1. read active tickers
2. fetch raw news
3. write raw rows to Bronze

Cleaning and scoring should still happen later in Silver.

The same principle now applies to market context:

- [05_fetch_market_context.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/05_fetch_market_context.py)
- [market_context_provider.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/market_context_provider.md)

That step should fetch raw quote/fundamental context and write it to Bronze before any business cleanup.

For holdings cleaning, the repo now includes:

- [06_clean_portfolio_data.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/06_clean_portfolio_data.py)
- [portfolio_cleaning_rules.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/portfolio_cleaning_rules.md)

This is the first real Silver cleanup step and prepares the data for news joins and Gold aggregation.

For news cleaning, the repo now includes:

- [07_clean_news_data.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/07_clean_news_data.py)
- [news_cleaning_rules.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/news_cleaning_rules.md)

This is the correct input-preparation stage before FinBERT scoring.

For sentiment scoring, the repo now includes:

- [08_score_news_with_finbert.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/08_score_news_with_finbert.py)
- [sentiment_scoring_rules.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/sentiment_scoring_rules.md)

This is the Silver scoring stage that produces the normalized sentiment outputs needed by Gold aggregation.

For Gold aggregation, the repo now includes:

- [09_aggregate_stock_gold_tables.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/09_aggregate_stock_gold_tables.py)
- [10_aggregate_portfolio_gold_tables.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/10_aggregate_portfolio_gold_tables.py)
- [gold_aggregation_rules.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/docs/gold_aggregation_rules.md)

This is the stage that produces the Databricks-first outputs your Django backend should eventually query.

The backend Databricks adapter path is now scaffolded through:

- [databricks_client.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/backend/analysis/databricks_client.py)
- [databricks_provider.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/backend/analysis/databricks_provider.py)
- [provider.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/backend/analysis/provider.py)

That means the API contract can stay stable while the provider switches from `demo` to `databricks`.

## Next production-ready step

Replace the heuristic backend service with a Databricks-backed repository layer:

1. Django calls Databricks SQL for `gold_stock_insight_current`
2. Django calls Databricks SQL for `gold_stock_news_view`
3. Django calls Databricks SQL for `gold_portfolio_summary`
4. Django uses `gold_stock_report_dataset` for report generation

## Two-branch rollout

Recommended approach:

1. Finish and verify this module on `main`
2. Cherry-pick the sentiment module commit onto `azureDeploy`
3. Resolve any deployment-only env differences there

If both branches diverge heavily, repeat the same file-level changes in the deployment branch while preserving branch-specific config.
