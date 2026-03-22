# Databricks Foundation

This folder contains the Databricks-first scaffolding for the stock insight module.

## Purpose

The app already has a working Django + React sentiment demo.
This folder prepares the real data platform path:

- Supabase/Postgres -> Databricks Bronze
- Bronze -> Silver cleaning/scoring
- Silver -> Gold stock insight outputs
- Django backend -> Databricks SQL -> React UI

## Folder layout

- `sql/01_medallion_schema.sql`
- `sql/02_gold_views.sql`
- `jobs/stock_insight_job.yml`
- `notebooks/README.md`
- `config/env.example`

## Execution order

1. Create medallion schemas and tables
2. Implement notebooks for ingestion and transforms
3. Create Lakeflow/Jobs workflow
4. Point backend to Databricks Gold outputs
