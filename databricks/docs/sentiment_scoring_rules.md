# Sentiment Scoring Rules

This document explains **Phase 5, Step 8 and Step 9**.

## Final recommendation

Use:

- **FinBERT as the main sentiment model**
- heuristic fallback only if the model is unavailable
- no LLM in the core scoring loop

This is the best fit for your project because it balances:

- financial-text relevance
- implementation realism
- runtime cost
- explainability

## Input table

The scoring step should read from:

- `silver_news_clean`

not from Bronze.

That is important because FinBERT should score:

- deduplicated
- normalized
- timestamp-clean
- usable text

## Output table

Write to:

- `silver_news_scored`

## Normalized fields

Each scored row should produce:

### `sentiment_label`

One of:

- `positive`
- `neutral`
- `negative`

### `confidence_score`

A numeric model confidence score.

### `normalized_score`

One of:

- `1`
- `0`
- `-1`

This is useful because Gold aggregation becomes simple and explainable.

### `relevance_score`

A simple score that estimates how strongly the article matches the ticker context.

### `impact_level`

One of:

- `low`
- `medium`
- `high`

### `event_type`

One of:

- `earnings`
- `analyst_rating`
- `guidance`
- `legal`
- `product`
- `management`
- `macro`
- `merger_acquisition`
- `dividend`
- `other`

## Why this normalized shape is good

This is the right structure because:

- the frontend does not need raw model logits
- Gold tables can aggregate directly
- report generation becomes easier
- risk flags and badges become explainable

## Current implementation behavior

The current notebook:

1. tries to load `ProsusAI/finbert`
2. scores the cleaned text
3. maps labels to normalized values
4. assigns event type
5. assigns impact level
6. computes relevance score

If FinBERT is not available, it falls back to a lightweight keyword-based method so development can keep moving.

## Why fallback exists

You may hit:

- package install issues
- cluster library issues
- runtime constraints

Fallback is useful for development continuity.
But for your final data-platform story, FinBERT remains the primary model.

## What comes next

The next correct step is:

- **Phase 6, Step 10 to Step 13**: Gold aggregation from `silver_news_scored`, `silver_portfolio_clean`, and market context
