-- Stock Insight Module
-- Databricks medallion foundation

CREATE SCHEMA IF NOT EXISTS portfolio_analyzer.bronze;
CREATE SCHEMA IF NOT EXISTS portfolio_analyzer.silver;
CREATE SCHEMA IF NOT EXISTS portfolio_analyzer.gold;

CREATE TABLE IF NOT EXISTS portfolio_analyzer.bronze.bronze_portfolio_snapshot (
  batch_id STRING,
  source_tag STRING,
  ingestion_ts TIMESTAMP,
  user_id STRING,
  portfolio_id STRING,
  ticker STRING,
  quantity DOUBLE,
  avg_buy_price DOUBLE,
  sector STRING,
  updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.bronze.bronze_news_raw (
  batch_id STRING,
  source_tag STRING,
  ingestion_ts TIMESTAMP,
  ticker STRING,
  source STRING,
  headline STRING,
  summary STRING,
  url STRING,
  published_at TIMESTAMP,
  raw_json STRING,
  fetch_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.bronze.bronze_market_data_raw (
  batch_id STRING,
  source_tag STRING,
  ingestion_ts TIMESTAMP,
  ticker STRING,
  last_price DOUBLE,
  daily_change_pct DOUBLE,
  pe_ratio DOUBLE,
  market_cap DOUBLE,
  earnings_context STRING,
  raw_json STRING,
  fetch_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.silver.silver_portfolio_clean (
  user_id STRING,
  portfolio_id STRING,
  ticker STRING,
  quantity DOUBLE,
  avg_buy_price DOUBLE,
  sector STRING,
  updated_at TIMESTAMP,
  as_of_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.silver.silver_active_ticker_list (
  ticker STRING,
  portfolio_count BIGINT,
  user_count BIGINT,
  latest_holding_update_ts TIMESTAMP,
  as_of_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.silver.silver_news_clean (
  ticker STRING,
  source STRING,
  headline STRING,
  summary STRING,
  url STRING,
  published_at TIMESTAMP,
  content_hash STRING,
  relevance_flag BOOLEAN,
  cleaned_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.silver.silver_news_scored (
  ticker STRING,
  source STRING,
  headline STRING,
  url STRING,
  published_at TIMESTAMP,
  sentiment_label STRING,
  confidence_score DOUBLE,
  normalized_score INT,
  relevance_score DOUBLE,
  impact_level STRING,
  event_type STRING,
  scored_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.silver.silver_market_data_clean (
  ticker STRING,
  last_price DOUBLE,
  daily_change_pct DOUBLE,
  pe_ratio DOUBLE,
  market_cap DOUBLE,
  earnings_context STRING,
  as_of_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.gold.gold_stock_insight_current (
  ticker STRING,
  sentiment_score_24h DOUBLE,
  sentiment_score_7d DOUBLE,
  news_count BIGINT,
  positive_count BIGINT,
  negative_count BIGINT,
  neutral_count BIGINT,
  high_impact_news_count BIGINT,
  dominant_event_type STRING,
  trend_direction STRING,
  last_price DOUBLE,
  daily_change_pct DOUBLE,
  pe_ratio DOUBLE,
  market_cap DOUBLE,
  as_of_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.gold.gold_stock_news_view (
  ticker STRING,
  cleaned_headline STRING,
  source STRING,
  published_at TIMESTAMP,
  sentiment_label STRING,
  impact_level STRING,
  short_explanation_tag STRING,
  url STRING
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.gold.gold_portfolio_summary (
  user_id STRING,
  portfolio_id STRING,
  portfolio_sentiment STRING,
  portfolio_sentiment_score DOUBLE,
  most_positive_stock STRING,
  most_risky_stock STRING,
  most_mentioned_stock STRING,
  sector_sentiment_mix STRING,
  as_of_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_analyzer.gold.gold_stock_report_dataset (
  ticker STRING,
  stock_name STRING,
  stock_snapshot STRING,
  sentiment_trend STRING,
  top_news_json STRING,
  risk_flags_json STRING,
  market_context_json STRING,
  executive_summary STRING,
  sentiment_explanation STRING,
  short_term_outlook STRING,
  risk_assessment STRING,
  verdict STRING,
  as_of_ts TIMESTAMP
);
