# Databricks notebook source
# Step 10/11: Build stock-level Gold tables.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Silver inputs

news_scored_df = spark.table("portfolio_analyzer.silver.silver_news_scored")
market_clean_df = spark.table("portfolio_analyzer.silver.silver_market_data_clean")


# COMMAND ----------
# Time windows for aggregation

scored_window_df = news_scored_df.withColumn(
    "hours_since_publish",
    (F.unix_timestamp(F.current_timestamp()) - F.unix_timestamp(F.col("published_at"))) / F.lit(3600.0),
)

scored_24h_df = scored_window_df.filter(F.col("hours_since_publish") <= 24)
scored_7d_df = scored_window_df.filter(F.col("hours_since_publish") <= 24 * 7)


# COMMAND ----------
# Aggregate 24h scores

agg_24h_df = (
    scored_24h_df.groupBy("ticker")
    .agg(
        F.sum(F.col("normalized_score") * F.col("confidence_score") * F.col("relevance_score")).alias("sentiment_score_24h"),
    )
)


# COMMAND ----------
# Aggregate 7d scores and counts

agg_7d_df = (
    scored_7d_df.groupBy("ticker")
    .agg(
        F.sum(F.col("normalized_score") * F.col("confidence_score") * F.col("relevance_score")).alias("sentiment_score_7d"),
        F.count("*").alias("news_count"),
        F.sum(F.when(F.col("sentiment_label") == "positive", 1).otherwise(0)).alias("positive_count"),
        F.sum(F.when(F.col("sentiment_label") == "negative", 1).otherwise(0)).alias("negative_count"),
        F.sum(F.when(F.col("sentiment_label") == "neutral", 1).otherwise(0)).alias("neutral_count"),
        F.sum(F.when(F.col("impact_level") == "high", 1).otherwise(0)).alias("high_impact_news_count"),
    )
)


# COMMAND ----------
# Dominant event type and trend direction

event_counts_df = (
    scored_7d_df.groupBy("ticker", "event_type")
    .agg(F.count("*").alias("event_count"))
)

event_rank_window = Window.partitionBy("ticker").orderBy(F.col("event_count").desc(), F.col("event_type").asc())
dominant_event_df = (
    event_counts_df.withColumn("rn", F.row_number().over(event_rank_window))
    .filter(F.col("rn") == 1)
    .select("ticker", F.col("event_type").alias("dominant_event_type"))
)


# COMMAND ----------
# Join market context and compute trend direction

gold_stock_insight_current_df = (
    agg_7d_df.join(agg_24h_df, on="ticker", how="left")
    .join(dominant_event_df, on="ticker", how="left")
    .join(market_clean_df, on="ticker", how="left")
    .withColumn("sentiment_score_24h", F.coalesce(F.col("sentiment_score_24h"), F.lit(0.0)))
    .withColumn(
        "trend_direction",
        F.when(F.col("sentiment_score_24h") > F.col("sentiment_score_7d"), F.lit("improving"))
        .when(F.col("sentiment_score_24h") < F.col("sentiment_score_7d"), F.lit("weakening"))
        .otherwise(F.lit("steady")),
    )
    .withColumn("as_of_ts", F.current_timestamp())
    .select(
        "ticker",
        F.round("sentiment_score_24h", 4).alias("sentiment_score_24h"),
        F.round("sentiment_score_7d", 4).alias("sentiment_score_7d"),
        "news_count",
        "positive_count",
        "negative_count",
        "neutral_count",
        "high_impact_news_count",
        F.coalesce(F.col("dominant_event_type"), F.lit("other")).alias("dominant_event_type"),
        "trend_direction",
        "last_price",
        "daily_change_pct",
        "pe_ratio",
        "market_cap",
        "as_of_ts",
    )
)


# COMMAND ----------
# Build frontend-ready Gold news view

short_tag_df = scored_7d_df.withColumn(
    "short_explanation_tag",
    F.when(F.col("event_type") == "earnings", F.lit("Earnings commentary is shaping sentiment"))
    .when(F.col("event_type") == "analyst_rating", F.lit("Broker activity is influencing the outlook"))
    .when(F.col("event_type") == "guidance", F.lit("Forward outlook is affecting near-term sentiment"))
    .when(F.col("event_type") == "legal", F.lit("Legal or regulatory risk is in focus"))
    .when(F.col("event_type") == "product", F.lit("Execution and deal flow are driving sentiment"))
    .when(F.col("event_type") == "management", F.lit("Leadership developments are influencing confidence"))
    .when(F.col("event_type") == "macro", F.lit("Macro conditions are driving the tone"))
    .when(F.col("event_type") == "merger_acquisition", F.lit("Deal activity is moving sentiment"))
    .when(F.col("event_type") == "dividend", F.lit("Shareholder return signals are supporting attention"))
    .otherwise(F.lit("General market news is shaping the tone"))
)

gold_stock_news_view_df = short_tag_df.select(
    "ticker",
    F.col("headline").alias("cleaned_headline"),
    "source",
    "published_at",
    "sentiment_label",
    "impact_level",
    "short_explanation_tag",
    "url",
)


# COMMAND ----------
# Write Gold tables

(
    gold_stock_insight_current_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.gold.gold_stock_insight_current")
)

(
    gold_stock_news_view_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.gold.gold_stock_news_view")
)


# COMMAND ----------
# Validation outputs

display(gold_stock_insight_current_df)
display(gold_stock_news_view_df.limit(20))
