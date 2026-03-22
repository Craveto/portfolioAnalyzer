# Portfolio Cleaning Rules

This document explains **Phase 4, Step 6** for your project.

## Goal of Step 6

Convert raw holdings in:

- `bronze_portfolio_snapshot`

into a cleaner, reliable Silver table:

- `silver_portfolio_clean`

This is the first place where we apply business-oriented validation.

## Why this step matters

Bronze is only for raw ingestion.
That means it can contain:

- inconsistent ticker casing
- blank sectors
- duplicate rows across batches
- older holding states
- invalid quantities or prices

If those problems stay in the data, then:

- news fetch can overcount tickers
- sentiment scoring can attach to stale holdings
- Gold portfolio summaries become misleading

So Step 6 is essential.

## Cleaning rules implemented

### 1. Normalize identifiers

- trim `user_id`
- trim `portfolio_id`
- uppercase and trim `ticker`

Why:

- avoids duplicate values like `tcs.ns` and `TCS.NS`
- keeps joins cleaner later

### 2. Standardize sector values

- trim sector
- apply title-style formatting
- fill missing sector with `Unknown`

Why:

- sector-level sentiment mix later depends on usable sector names

### 3. Validate quantity

Keep only rows where:

- `quantity` is not null
- `quantity` > 0

Why:

- active holdings should be positive
- zero and negative rows do not belong in the active holdings state table

### 4. Validate average buy price

Keep only rows where:

- `avg_buy_price` is not null
- `avg_buy_price` >= 0

Why:

- negative buy prices are invalid for this use case

### 5. Keep latest holding state

For each:

- `user_id`
- `portfolio_id`
- `ticker`

keep the latest row based on:

1. `updated_at`
2. `ingestion_ts`

Why:

- the current pipeline needs the latest active holding state, not every raw snapshot row

## Why this fits your project

Your Django app already maintains current holding state in the database.
So Silver should represent the latest clean analytical version of that same state.

It should not yet become a transaction-history table.

That means this step is exactly right for:

- ticker list generation
- per-stock joins
- portfolio-level aggregation
- frontend stock insight alignment

## What is completed after this step

After live execution, you will have:

- standardized holdings
- validated positive quantities
- one clean current row per portfolio/ticker
- a trustworthy base for Silver news cleaning and Gold joins

## What comes next

The next correct step is:

- **Phase 4, Step 7**: clean and normalize news into `silver_news_clean`
