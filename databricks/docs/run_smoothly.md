# How To Run Smoothly in VS Code and Databricks

This is the practical checklist I recommend for your project.

## 1. Keep responsibilities separate

### In VS Code

Use VS Code for:

- Django backend changes
- React frontend changes
- local testing
- writing Databricks SQL/notebook files
- version control across branches

### In Databricks

Use Databricks for:

- JDBC ingestion from Supabase
- medallion table writes
- news fetch jobs
- FinBERT scoring
- Gold aggregations

Do not try to turn your Django app into the data pipeline engine.
Let Django consume the final outputs.

## 2. Keep one provider active at a time

Use:

- `STOCK_INSIGHT_PROVIDER=demo` while building and demoing locally
- `STOCK_INSIGHT_PROVIDER=databricks` only after Gold tables are ready

This avoids breaking your current UI while Databricks is still under construction.

## 3. Use one source of truth for schema

Your current truth for portfolio holdings is Supabase Postgres.

So:

- edit holdings only through Django/backend
- ingest holdings into Databricks from Supabase
- never manually duplicate holdings in Databricks tables

That keeps sync problems low.

## 4. Make notebooks idempotent

Each Databricks notebook should be safe to rerun.

Best practice:

- Bronze writes can be `append`
- Silver writes can be `overwrite` or `merge`
- Gold writes should be deterministic from Silver

This makes debugging much easier.

## 5. Validate every stage before moving on

Before going to the next workflow step:

- check row counts
- check distinct tickers
- check null columns
- check sample records
- check timestamps

This is why the Bronze validation notebook exists.

## 6. Keep environment values outside code

Do not hardcode:

- Supabase password
- Databricks token
- warehouse path
- provider keys

Use:

- local `.env` for Django
- Databricks secret scopes or job parameters for notebooks
- env templates in `databricks/config/env.example`

## 7. Use small test data first

For smooth runs, start with:

- 1 user
- 1 portfolio
- 3 to 5 holdings
- 3 to 5 tickers

Only after that works, scale to more tickers.

This matters especially for news APIs and FinBERT runtime cost.

## 8. Recommended branch discipline

Since you have two branches:

### `main`

Use for:

- feature development
- notebook/sql scaffolding
- backend/frontend contract work

### `azureDeploy`

Use for:

- deployment-safe config
- final release wiring
- branch-specific environment adjustments

Best practice:

1. finish the feature on `main`
2. verify it locally
3. commit clearly
4. cherry-pick to `azureDeploy`
5. test deployment-specific issues there

## 9. Suggested local workflow in VS Code

Each time:

1. pull latest branch
2. run backend
3. run frontend
4. change one small step
5. verify
6. commit

Do not mix:

- sentiment UI changes
- Databricks ingestion changes
- deployment fixes

in one messy commit if you can avoid it.

## 10. Suggested Databricks workflow

Do this order:

1. run `01_medallion_schema.sql`
2. run `01_ingest_supabase_portfolio.py`
3. run `02_validate_bronze_portfolio_snapshot.py`
4. run `03_build_active_ticker_list.py`
5. inspect `silver_active_ticker_list`
6. only then start news ingestion

That is the smoothest path.

## 11. What can break things most often

Watch out for:

- wrong Postgres schema name
- wrong JDBC driver availability
- Supabase network allow/block issues
- uppercase/lowercase ticker inconsistencies
- null sector values
- empty holdings
- frontend expecting Gold-like fields before backend returns them

## 12. My strongest suggestion for your project

For your deadline, do this:

1. keep the current demo module working in Django
2. continue building Databricks steps as scaffolding plus executable notebooks
3. demo the working UI now
4. explain that Databricks is being connected underneath the same contract

This is the safest way to finish on time without destabilizing the app.
