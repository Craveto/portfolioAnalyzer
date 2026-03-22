# Databricks notebook source
# Step 12/13: Build portfolio summary and report-ready Gold dataset.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Silver and Gold inputs

portfolio_clean_df = spark.table("portfolio_analyzer.silver.silver_portfolio_clean")
stock_insight_df = spark.table("portfolio_analyzer.gold.gold_stock_insight_current")
stock_news_view_df = spark.table("portfolio_analyzer.gold.gold_stock_news_view")


# COMMAND ----------
# Join holdings with stock insight

portfolio_stock_df = (
    portfolio_clean_df.join(stock_insight_df, on="ticker", how="left")
    .select(
        "user_id",
        "portfolio_id",
        "ticker",
        "sector",
        "quantity",
        "avg_buy_price",
        "sentiment_score_7d",
        "news_count",
        "high_impact_news_count",
        "dominant_event_type",
        "last_price",
        "daily_change_pct",
        "pe_ratio",
        "market_cap",
    )
)


# COMMAND ----------
# Portfolio-level summary

portfolio_sentiment_df = (
    portfolio_stock_df.groupBy("user_id", "portfolio_id")
    .agg(
        F.avg("sentiment_score_7d").alias("portfolio_sentiment_score"),
    )
    .withColumn(
        "portfolio_sentiment",
        F.when(F.col("portfolio_sentiment_score") >= 1.0, F.lit("Bullish"))
        .when(F.col("portfolio_sentiment_score") <= -1.0, F.lit("Bearish"))
        .otherwise(F.lit("Neutral")),
    )
)

positive_window = Window.partitionBy("user_id", "portfolio_id").orderBy(F.col("sentiment_score_7d").desc_nulls_last(), F.col("ticker"))
risk_window = Window.partitionBy("user_id", "portfolio_id").orderBy(F.col("high_impact_news_count").desc_nulls_last(), F.col("sentiment_score_7d").asc_nulls_last(), F.col("ticker"))
mention_window = Window.partitionBy("user_id", "portfolio_id").orderBy(F.col("news_count").desc_nulls_last(), F.col("ticker"))

most_positive_df = (
    portfolio_stock_df.withColumn("rn", F.row_number().over(positive_window))
    .filter(F.col("rn") == 1)
    .select("user_id", "portfolio_id", F.col("ticker").alias("most_positive_stock"))
)

most_risky_df = (
    portfolio_stock_df.withColumn("rn", F.row_number().over(risk_window))
    .filter(F.col("rn") == 1)
    .select("user_id", "portfolio_id", F.col("ticker").alias("most_risky_stock"))
)

most_mentioned_df = (
    portfolio_stock_df.withColumn("rn", F.row_number().over(mention_window))
    .filter(F.col("rn") == 1)
    .select("user_id", "portfolio_id", F.col("ticker").alias("most_mentioned_stock"))
)

sector_mix_df = (
    portfolio_stock_df.groupBy("user_id", "portfolio_id", "sector")
    .agg(F.avg("sentiment_score_7d").alias("sector_avg_sentiment_score"))
    .groupBy("user_id", "portfolio_id")
    .agg(
        F.to_json(
            F.collect_list(
                F.struct(
                    F.col("sector"),
                    F.round(F.col("sector_avg_sentiment_score"), 4).alias("avg_sentiment_score"),
                )
            )
        ).alias("sector_sentiment_mix")
    )
)

gold_portfolio_summary_df = (
    portfolio_sentiment_df.join(most_positive_df, on=["user_id", "portfolio_id"], how="left")
    .join(most_risky_df, on=["user_id", "portfolio_id"], how="left")
    .join(most_mentioned_df, on=["user_id", "portfolio_id"], how="left")
    .join(sector_mix_df, on=["user_id", "portfolio_id"], how="left")
    .withColumn("as_of_ts", F.current_timestamp())
    .select(
        "user_id",
        "portfolio_id",
        "portfolio_sentiment",
        F.round("portfolio_sentiment_score", 4).alias("portfolio_sentiment_score"),
        "most_positive_stock",
        "most_risky_stock",
        "most_mentioned_stock",
        "sector_sentiment_mix",
        "as_of_ts",
    )
)


# COMMAND ----------
# Report-ready dataset per stock

news_rank_window = Window.partitionBy("ticker").orderBy(F.col("published_at").desc_nulls_last(), F.col("impact_level").asc())
top_news_df = (
    stock_news_view_df.withColumn("rn", F.row_number().over(news_rank_window))
    .filter(F.col("rn") <= 3)
    .groupBy("ticker")
    .agg(
        F.to_json(
            F.collect_list(
                F.struct(
                    F.col("cleaned_headline").alias("headline"),
                    F.col("source"),
                    F.col("published_at"),
                    F.col("sentiment_label"),
                    F.col("impact_level"),
                    F.col("short_explanation_tag"),
                    F.col("url"),
                )
            )
        ).alias("top_news_json")
    )
)

risk_flags_df = (
    stock_news_view_df.withColumn(
        "risk_flag",
        F.when(F.col("impact_level") == "high", F.concat(F.initcap(F.col("sentiment_label")), F.lit(" high-impact news")))
        .when(F.col("sentiment_label") == "negative", F.lit("Negative news flow"))
        .otherwise(F.lit(None)),
    )
    .filter(F.col("risk_flag").isNotNull())
    .groupBy("ticker")
    .agg(F.to_json(F.collect_set("risk_flag")).alias("risk_flags_json"))
)

gold_stock_report_dataset_df = (
    stock_insight_df.join(top_news_df, on="ticker", how="left")
    .join(risk_flags_df, on="ticker", how="left")
    .withColumn(
        "stock_snapshot",
        F.to_json(
            F.struct(
                F.col("ticker"),
                F.col("last_price"),
                F.col("daily_change_pct"),
                F.col("pe_ratio"),
                F.col("market_cap"),
            )
        ),
    )
    .withColumn(
        "sentiment_trend",
        F.to_json(
            F.struct(
                F.col("sentiment_score_24h"),
                F.col("sentiment_score_7d"),
                F.col("trend_direction"),
                F.col("news_count"),
            )
        ),
    )
    .withColumn(
        "market_context_json",
        F.to_json(
            F.struct(
                F.col("last_price"),
                F.col("daily_change_pct"),
                F.col("pe_ratio"),
                F.col("market_cap"),
                F.col("dominant_event_type"),
            )
        ),
    )
    .withColumn(
        "executive_summary",
        F.concat(
            F.lit("Recent sentiment around "),
            F.col("ticker"),
            F.lit(" is being driven mainly by "),
            F.coalesce(F.col("dominant_event_type"), F.lit("general")),
            F.lit(" news flow."),
        ),
    )
    .withColumn(
        "sentiment_explanation",
        F.concat(
            F.lit("The 7-day sentiment score is "),
            F.col("sentiment_score_7d").cast("string"),
            F.lit(" with "),
            F.col("news_count").cast("string"),
            F.lit(" relevant articles."),
        ),
    )
    .withColumn(
        "short_term_outlook",
        F.concat(F.lit("Trend direction is currently "), F.col("trend_direction"), F.lit(".")),
    )
    .withColumn(
        "risk_assessment",
        F.when(F.col("high_impact_news_count") > 0, F.lit("High-impact headlines are present and should be monitored closely."))
        .otherwise(F.lit("No major high-impact headline concentration detected.")),
    )
    .withColumn(
        "verdict",
        F.when(F.col("sentiment_score_7d") >= 1.0, F.lit("Bullish"))
        .when(F.col("sentiment_score_7d") <= -1.0, F.lit("Bearish"))
        .otherwise(F.lit("Neutral")),
    )
    .withColumn("stock_name", F.col("ticker"))
    .withColumn("as_of_ts", F.current_timestamp())
    .select(
        "ticker",
        "stock_name",
        "stock_snapshot",
        "sentiment_trend",
        "top_news_json",
        "risk_flags_json",
        "market_context_json",
        "executive_summary",
        "sentiment_explanation",
        "short_term_outlook",
        "risk_assessment",
        "verdict",
        "as_of_ts",
    )
)


# COMMAND ----------
# Write Gold tables

(
    gold_portfolio_summary_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.gold.gold_portfolio_summary")
)

(
    gold_stock_report_dataset_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.gold.gold_stock_report_dataset")
)


# COMMAND ----------
# Validation outputs

# display(gold_portfolio_summary_df)
# display(gold_stock_report_dataset_df.limit(20))
