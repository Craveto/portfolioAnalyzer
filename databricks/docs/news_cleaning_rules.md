# News Cleaning Rules

This document explains **Phase 4, Step 7** for your project.

## Goal of Step 7

Convert raw news in:

- `bronze_news_raw`

into a cleaner Silver dataset:

- `silver_news_clean`

This is the layer that should be passed to the sentiment model later.

## Why this step matters

Raw news often contains:

- duplicate articles
- repeated provider copies
- HTML fragments
- noisy whitespace
- empty or tiny headlines
- timestamp inconsistencies

If you score that directly, the sentiment stage becomes noisy and misleading.

That is why Step 7 is necessary before FinBERT.

## Cleaning rules implemented

### 1. Normalize identifiers

- uppercase and trim `ticker`
- trim `source`
- trim `url`

Why:

- later joins and group-bys should not depend on casing differences

### 2. Clean text

- strip HTML from `headline`
- strip HTML from `summary`
- normalize whitespace
- trim both fields

Why:

- sentiment models work better on normalized text
- the frontend also benefits from cleaner text later

### 3. Normalize timestamp

- cast `published_at` to timestamp

Why:

- later 24h and 7d windows depend on valid timestamps

### 4. Remove unusable rows

Keep only rows where:

- `ticker` exists
- `headline` exists
- headline length is at least 12 characters

Why:

- tiny or blank headlines are rarely useful for financial sentiment

### 5. Deduplicate

Build a `content_hash` using:

- ticker
- headline
- source
- url

Then keep the latest row per content hash.

Why:

- provider feeds often repeat the same article shape
- duplicate rows would distort sentiment counts

### 6. Relevance flag

The current template keeps a simple `relevance_flag`.

For now:

- rows remain marked as relevant if they are tied to the fetched ticker and have a usable headline

Later you can make this stricter with:

- company-name matching
- named entity checks
- ticker alias mapping

## Why this fits your project

You need a clean and explainable flow.
This step is strong because it is:

- simple enough to finish on time
- realistic enough for a proper data pipeline
- easy to explain to your teacher

## What is completed after this step

After live execution, you will have:

- deduplicated article rows
- clean headline/summary text
- normalized timestamps
- a safe input table for sentiment scoring

## What comes next

The next step is:

- **Phase 5, Step 8/9**: FinBERT-based sentiment scoring into `silver_news_scored`
