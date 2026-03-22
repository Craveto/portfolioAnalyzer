# Market Context Provider Recommendation

This document explains the best path for **Phase 3, Step 5**.

## Goal of Step 5

Fetch context that makes sentiment explainable:

- latest price
- daily change
- P/E if available
- market cap if available
- earnings context if available

Store it raw first in:

- `bronze_market_data_raw`

## Best practical provider path

For your current deadline:

- start with **Finnhub** for quote and profile context
- keep `pe_ratio` and `earnings_context` nullable for now

Why this is still acceptable:

- price and market cap already improve the analyst view a lot
- you can fill stronger fundamentals later in Silver or with another provider
- it keeps the pipeline moving

## Why not block Step 5 on perfect fundamentals

If you wait for perfect P/E and earnings fields before continuing:

- you lose time
- the pipeline stops
- the frontend cannot evolve

Better approach:

1. get quote context working first
2. store raw payloads
3. enrich fundamentals later

That is more realistic for your project schedule.

## Current provider caveat for Indian tickers

Like Step 4, some providers expect base symbols:

- `INFY.NS` -> `INFY`

The notebook handles this by stripping the Yahoo suffix before calling Finnhub.

Later you should introduce a symbol mapping table if coverage is inconsistent.

## What the current notebook writes

- `batch_id`
- `source_tag`
- `ingestion_ts`
- `ticker`
- `last_price`
- `daily_change_pct`
- `pe_ratio`
- `market_cap`
- `earnings_context`
- `raw_json`
- `fetch_ts`

This is correct for Bronze because:

- it preserves raw context
- it keeps fields nullable
- it does not force business logic too early

## Smooth-run suggestions for Step 5

1. run after `silver_active_ticker_list` is ready
2. start with `max_tickers=5`
3. accept null `pe_ratio` initially
4. keep raw JSON for debugging
5. do not merge this logic with Silver cleaning yet

## What should happen later

Later improvements can include:

- earnings calendar provider
- stronger fundamentals source
- P/E backfill
- symbol mapping table for NSE/BSE names
- deduplicated latest context in Silver

## Current completion state

What is done now:

- Step 5 notebook template exists
- Bronze write path exists
- provider guidance exists

What is not done yet:

- live provider-backed execution
- Silver market cleaning
- use of final market context inside Gold aggregation
