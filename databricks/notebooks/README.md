# Notebook Breakdown

Create one notebook per task in the job workflow.

## Notebook list

1. `01_ingest_supabase_portfolio`
2. `02_validate_bronze_portfolio_snapshot`
3. `03_build_active_ticker_list`
4. `04_fetch_news_for_tickers`
5. `05_fetch_market_context`
6. `06_clean_portfolio_data`
7. `07_clean_news_data`
8. `08_score_news_with_finbert`
9. `09_aggregate_stock_gold_tables`
10. `10_aggregate_portfolio_gold_tables`

## What each notebook should do

### 01_ingest_supabase_portfolio

- Read holdings from Supabase Postgres with JDBC
- Add `batch_id`, `source_tag`, `ingestion_ts`
- Write to `bronze_portfolio_snapshot`
- Current template file exists in this repo as `01_ingest_supabase_portfolio.py`

### 02_validate_bronze_portfolio_snapshot

- Check row counts, nulls, and non-positive quantities
- Validate that Bronze is usable before downstream tasks

### 03_build_active_ticker_list

- Read clean/latest holdings
- Generate distinct active ticker universe
- Persist `silver_active_ticker_list`

### 04_fetch_news_for_tickers

- Read `silver_active_ticker_list`
- Fetch raw news from one provider
- Write untouched payload to `bronze_news_raw`

### 05_fetch_market_context

- Read `silver_active_ticker_list`
- Fetch quote/fundamental context
- Write raw rows to `bronze_market_data_raw`

### 06_clean_portfolio_data

- Normalize ticker and identifier fields
- validate quantity and average buy price
- standardize sectors
- keep latest active holding state
- write `silver_portfolio_clean`

### 07_clean_news_data

- normalize ticker/source/text fields
- strip HTML and normalize whitespace
- remove unusable rows
- deduplicate by content shape
- write `silver_news_clean`

### 08_score_news_with_finbert

- score clean news with FinBERT
- normalize label, confidence, score, impact, and event type
- write `silver_news_scored`

### 09_aggregate_stock_gold_tables

- aggregate scored sentiment into stock-level Gold outputs
- build `gold_stock_insight_current`
- build `gold_stock_news_view`

### 10_aggregate_portfolio_gold_tables

- aggregate portfolio-level Gold outputs
- build `gold_portfolio_summary`
- build `gold_stock_report_dataset`

### 03_fetch_news_for_tickers

- Fetch raw ticker news from the chosen provider
- Store untouched payload in `bronze_news_raw`

### 04_fetch_market_context

- Fetch last price, daily change, P/E, market cap, earnings context
- Store raw payload in `bronze_market_data_raw`

### 05_clean_portfolio_data

- Normalize ticker casing
- Validate quantity and average buy price
- Keep latest holding state
- Write `silver_portfolio_clean`

### 06_clean_news_data

- Remove duplicates
- Strip HTML
- Standardize timezone
- Drop irrelevant or too-short rows
- Write `silver_news_clean`

### 07_score_news_with_finbert

- Score clean news with FinBERT
- Add `sentiment_label`, `confidence_score`, `normalized_score`, `impact_level`, `event_type`
- Write `silver_news_scored`

### 08_aggregate_stock_gold_tables

- Build `gold_stock_insight_current`
- Build `gold_stock_news_view`

### 09_aggregate_portfolio_gold_tables

- Build `gold_portfolio_summary`

### 10_build_report_dataset

- Build `gold_stock_report_dataset`
- Keep it small and report-ready for backend consumption
