# Gold Aggregation Rules

This document explains **Phase 6, Step 10 to Step 13**.

## Goal of the Gold layer

Gold is where the pipeline becomes business-ready.

It should produce:

- stock-level insight
- frontend-ready news feed rows
- portfolio-level sentiment summary
- report-ready stock datasets

That is why Gold is the correct layer for backend API consumption.

## Gold tables in this project

### `gold_stock_insight_current`

This is the main stock-level aggregate.

Per ticker it should answer:

- 24h sentiment score
- 7d sentiment score
- news count
- positive count
- negative count
- neutral count
- high-impact news count
- dominant event type
- trend direction
- price/fundamental context

### `gold_stock_news_view`

This is a frontend-ready news feed table.

Each row should already contain:

- ticker
- cleaned headline
- source
- published time
- sentiment label
- impact level
- short explanation tag
- url

This is the table your website can render directly.

### `gold_portfolio_summary`

This is the portfolio-level sentiment aggregate.

It should answer:

- portfolio sentiment
- portfolio sentiment score
- most positive stock
- most risky stock
- most mentioned stock
- sector sentiment mix

### `gold_stock_report_dataset`

This is the report-ready stock dataset.

It should contain:

- stock snapshot
- sentiment trend
- top news
- risk flags
- market context
- executive summary
- sentiment explanation
- short-term outlook
- risk assessment
- verdict

## Why this fits your project

Your frontend and backend should not need to re-derive analytics every time.
That would make the app:

- slower
- harder to explain
- more fragile

Gold tables solve that by giving Django a curated analytics product to query.

## Current implementation logic

### Stock insight aggregation

The current notebook:

- aggregates 24h and 7d scored sentiment
- counts positive/negative/neutral rows
- counts high-impact headlines
- detects dominant event type
- joins market context
- derives trend direction

### News view shaping

The current notebook:

- takes scored Silver news
- attaches a short explanation tag
- outputs UI-ready rows

### Portfolio summary aggregation

The current notebook:

- averages stock sentiment per portfolio
- identifies the most positive stock
- identifies the most risky stock
- identifies the most mentioned stock
- creates sector sentiment mix as JSON

### Report dataset shaping

The current notebook:

- selects top 3 news items per ticker
- builds JSON fields for snapshot, trend, top news, and risk flags
- adds short textual summary columns

## What comes next

After Gold is ready, the next correct step is:

- backend querying these Gold outputs instead of relying on the demo provider

That is the bridge from Databricks pipeline to Django API.
