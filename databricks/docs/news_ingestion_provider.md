# News Ingestion Provider Recommendation

This document explains the best news-provider path for your project.

## Final recommendation

Use **Finnhub first** for the Databricks ingestion workflow.

Why:

- simple REST API
- easy to call from Databricks notebooks
- good enough for MVP and demo flow
- straightforward raw JSON storage in Bronze

## Why not overcomplicate provider choice right now

You need to finish the module quickly.
The project already has:

- Django
- React
- Supabase
- Databricks scaffolding
- a working teacher-demo UI

So the best move is:

1. pick one provider
2. build the pipeline shape correctly
3. keep provider replacement possible later

Finnhub fits that plan.

## What Step 4 should do

Step 4 is only responsible for:

- reading active tickers from `silver_active_ticker_list`
- fetching raw news
- storing the untouched payload in `bronze_news_raw`

It should not:

- deduplicate aggressively
- classify sentiment
- create explanations
- build frontend-ready cards

Those belong to Silver and Gold.

## Current ticker caveat for your project

Your app is focused on Indian market symbols like:

- `RELIANCE.NS`
- `TCS.NS`
- `INFY.NS`

Some providers expect a base symbol instead of the full Yahoo suffix.

That is why the notebook currently converts:

- `RELIANCE.NS` -> `RELIANCE`

This is acceptable for early scaffolding, but later you should verify symbol coverage carefully per provider.

## Bronze fields stored

The current notebook writes:

- `batch_id`
- `source_tag`
- `ingestion_ts`
- `ticker`
- `source`
- `headline`
- `summary`
- `url`
- `published_at`
- `raw_json`
- `fetch_ts`

This is correct for Bronze because it preserves the provider payload for later cleaning.

## Smooth-run suggestions for Step 4

For fewer problems:

1. start with `max_tickers=5`
2. use `days_back=7`
3. confirm `silver_active_ticker_list` is populated first
4. keep the raw JSON column always
5. log failed requests as error rows instead of crashing the whole batch

That is exactly how the current template is written.

## What to improve later

Later you can add:

- provider retry logic
- request throttling
- symbol mapping table for Indian tickers
- multi-provider fallback
- better error tracking

## Current completion state

What is done now:

- Step 4 notebook template exists
- provider contract exists
- Bronze raw news write path exists

What is not done yet:

- live Databricks execution with real provider key
- Silver news cleaning
- Silver sentiment scoring
