-- Gold queries and example UI-serving shapes

CREATE OR REPLACE VIEW portfolio_analyzer.gold.v_stock_signal_cards AS
SELECT
  ticker,
  CASE
    WHEN sentiment_score_7d >= 1.0 THEN 'Bullish'
    WHEN sentiment_score_7d <= -1.0 THEN 'Bearish'
    ELSE 'Neutral'
  END AS signal_label,
  sentiment_score_24h,
  sentiment_score_7d,
  news_count,
  high_impact_news_count,
  dominant_event_type,
  trend_direction,
  last_price,
  daily_change_pct,
  pe_ratio,
  market_cap,
  as_of_ts
FROM portfolio_analyzer.gold.gold_stock_insight_current;

CREATE OR REPLACE VIEW portfolio_analyzer.gold.v_portfolio_sentiment_cards AS
SELECT
  user_id,
  portfolio_id,
  portfolio_sentiment,
  portfolio_sentiment_score,
  most_positive_stock,
  most_risky_stock,
  most_mentioned_stock,
  sector_sentiment_mix,
  as_of_ts
FROM portfolio_analyzer.gold.gold_portfolio_summary;

CREATE OR REPLACE VIEW portfolio_analyzer.gold.v_report_download_dataset AS
SELECT
  ticker,
  stock_name,
  executive_summary,
  sentiment_explanation,
  short_term_outlook,
  risk_assessment,
  verdict,
  top_news_json,
  risk_flags_json,
  market_context_json,
  as_of_ts
FROM portfolio_analyzer.gold.gold_stock_report_dataset;
