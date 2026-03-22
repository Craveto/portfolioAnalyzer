# Stock Insight Workflow Tracker

This file keeps every planned workflow step visible so we do not lose any phase.

## Current status summary

- Completed now:
  - Step 6 style UI contract and stock insight module in the current app
  - Backend API contract for sentiment, stock insight, and report downloads
  - Report outputs: Markdown, CSV, Print-to-PDF flow
  - Databricks-ready response shape in Django
- In progress now:
  - Step 1 Databricks foundation scaffolding inside the repo
- Not completed yet:
  - Live Supabase to Databricks ingestion
  - Live external news + market ingestion into Bronze
  - FinBERT scoring in Databricks Silver
  - Gold-table backed backend queries

## Planned workflow checklist

### Phase 1 - Databricks foundation

- [x] Step 1: Define medallion architecture and Gold-style API contract in the repo
- [ ] Step 1A: Create Databricks catalogs/schemas/tables
- [ ] Step 1B: Create Databricks job workflow definition
- [ ] Step 1C: Add environment/config contract for Databricks access from backend

### Phase 2 - Pull portfolio data from Supabase

- [ ] Step 2: Read holdings from Supabase into Databricks Bronze
- [x] Step 2A: Add JDBC connection details and ingestion notebook
- [x] Step 2B: Add Bronze validation/output notebook for `bronze_portfolio_snapshot`
- [ ] Step 2C: Execute live Bronze write in Databricks workspace

### Phase 3 - Fetch external stock news and market context

- [x] Step 3: Build active ticker list notebook and Silver output contract
- [x] Step 4: Add news ingestion notebook template for active tickers into `bronze_news_raw`
- [ ] Step 4A: Execute live provider-backed news ingestion in Databricks
- [x] Step 5: Add market context ingestion notebook template for `bronze_market_data_raw`
- [ ] Step 5A: Execute live provider-backed market context ingestion in Databricks

### Phase 4 - Clean and normalize in Silver

- [x] Step 6: Add holdings cleaning notebook for `silver_portfolio_clean`
- [ ] Step 6A: Execute live Silver holdings cleaning in Databricks
- [x] Step 7: Add news cleaning notebook for `silver_news_clean`
- [ ] Step 7A: Execute live Silver news cleaning in Databricks

### Phase 5 - Sentiment engine

- [x] Step 8: Add FinBERT as primary scoring engine
- [x] Step 9: Normalize output into label, confidence, score, impact, event type
- [x] Step 9A: Add scoring notebook for `silver_news_scored`
- [ ] Step 9B: Execute live FinBERT scoring in Databricks

### Phase 6 - Aggregate into Gold

- [x] Step 10: Add Gold stock aggregation notebook for `gold_stock_insight_current`
- [x] Step 11: Add Gold stock news notebook logic for `gold_stock_news_view`
- [x] Step 12: Add Gold portfolio aggregation notebook for `gold_portfolio_summary`
- [x] Step 13: Add Gold report dataset notebook logic for `gold_stock_report_dataset`
- [ ] Step 13A: Execute live Gold aggregation in Databricks

### Phase 7 - LLM after aggregation

- [ ] Step 14: Add backend on-demand explanation/report generation using Gold inputs

### Phase 8 - Report generation workflow

- [x] Step 15A: Markdown report download
- [x] Step 15B: CSV report download
- [x] Step 15C: PDF-friendly print flow
- [ ] Step 15D: Persist generated report history and file metadata

### Phase 9 - Website integration

- [x] Backend endpoint contract for stock insight
- [x] Frontend stock insight cards
- [x] Frontend risk/news/explanation blocks
- [x] Add backend Databricks provider adapter scaffold
- [ ] Switch backend from heuristic/demo provider to live Databricks Gold provider in deployment

## What to tell your teacher today

You can honestly say:

1. The stock insight module and report flow are working in the app now.
2. The response contract is already shaped like a Databricks Gold output.
3. The next engineering step is to connect Databricks Bronze/Silver/Gold underneath the existing UI and APIs.
