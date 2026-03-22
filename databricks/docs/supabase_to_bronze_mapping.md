# Supabase to Bronze Mapping

This is the exact mapping for **Phase 2, Step 2** in your workflow.

## Why this step matters

Your app already stores the portfolio truth in Supabase Postgres through Django.
Databricks should not guess holdings from the frontend.
It should ingest the trusted backend database state first.

That is why this step reads from Supabase into `bronze_portfolio_snapshot`.

## Current source tables in this project

Based on the Django models, the expected Postgres tables are:

- `auth_user`
- `portfolio_portfolio`
- `portfolio_holding`
- `portfolio_stock`
- `portfolio_sector`

## Current source model meaning

### `portfolio_portfolio`

- owner portfolio record
- contains `user_id`

### `portfolio_holding`

- current holding state per portfolio and stock
- contains:
  - `portfolio_id`
  - `stock_id`
  - `qty`
  - `avg_buy_price`
  - `updated_at`

### `portfolio_stock`

- stock master lookup
- contains:
  - `symbol`
  - `name`
  - `exchange`
  - `sector_id`

### `portfolio_sector`

- sector lookup
- contains:
  - `name`

## Bronze target mapping

| Bronze column | Source |
|---|---|
| `batch_id` | generated in Databricks |
| `source_tag` | fixed value like `supabase_postgres` |
| `ingestion_ts` | current timestamp in Databricks |
| `user_id` | `portfolio_portfolio.user_id` |
| `portfolio_id` | `portfolio_holding.portfolio_id` |
| `ticker` | `portfolio_stock.symbol` |
| `quantity` | `portfolio_holding.qty` |
| `avg_buy_price` | `portfolio_holding.avg_buy_price` |
| `sector` | `portfolio_sector.name` |
| `updated_at` | `portfolio_holding.updated_at` |

## Why we do not transform much yet

Bronze is supposed to be raw and traceable.
So in this step:

- we preserve source meaning
- we add ingestion metadata
- we do not deduplicate heavily
- we do not standardize business logic yet

Cleaning belongs to Silver.

## Notebook that implements this step

Use:

- [01_ingest_supabase_portfolio.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/01_ingest_supabase_portfolio.py)

## What is completed after this step

After live execution in Databricks, you will have:

- Supabase holdings landing in Bronze
- a batch-traceable ingestion record
- the correct foundation for ticker-list generation in Step 3

## What is still not completed after this step

- active ticker list
- external news fetch
- market context fetch
- Silver cleaning
- FinBERT sentiment scoring
- Gold aggregates
