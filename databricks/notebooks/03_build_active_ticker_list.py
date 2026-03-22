# Databricks notebook source
# Step 3: Build distinct active ticker list from holdings.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Bronze snapshot

bronze_df = spark.table("portfolio_analyzer.bronze.bronze_portfolio_snapshot")


# COMMAND ----------
# Keep latest row per portfolio/ticker pair.
# This is the minimum clean-up needed to derive active tickers.

latest_window = Window.partitionBy("portfolio_id", "ticker").orderBy(
    F.col("updated_at").desc_nulls_last(),
    F.col("ingestion_ts").desc_nulls_last(),
)

latest_holdings_df = (
    bronze_df.filter(F.col("ticker").isNotNull())
    .filter(F.trim(F.col("ticker")) != "")
    .withColumn("ticker", F.upper(F.trim(F.col("ticker"))))
    .withColumn("rn", F.row_number().over(latest_window))
    .filter(F.col("rn") == 1)
    .drop("rn")
    .filter(F.col("quantity").isNotNull())
    .filter(F.col("quantity") > 0)
)

display(latest_holdings_df.limit(20))


# COMMAND ----------
# Persist a Silver-ready holdings table.
# This is still light cleaning and feeds the active ticker list.

silver_portfolio_clean_df = latest_holdings_df.select(
    "user_id",
    "portfolio_id",
    "ticker",
    F.col("quantity").cast("double").alias("quantity"),
    F.col("avg_buy_price").cast("double").alias("avg_buy_price"),
    F.trim(F.col("sector")).alias("sector"),
    "updated_at",
    F.current_timestamp().alias("as_of_ts"),
)

(
    silver_portfolio_clean_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_portfolio_clean")
)


# COMMAND ----------
# Build distinct active ticker list.

active_tickers_df = (
    silver_portfolio_clean_df.groupBy("ticker")
    .agg(
        F.countDistinct("portfolio_id").alias("portfolio_count"),
        F.countDistinct("user_id").alias("user_count"),
        F.max("updated_at").alias("latest_holding_update_ts"),
    )
    .withColumn("as_of_ts", F.current_timestamp())
    .orderBy("ticker")
)

(
    active_tickers_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_active_ticker_list")
)


# COMMAND ----------
# Validation output

display(active_tickers_df)
display(
    active_tickers_df.agg(
        F.count("*").alias("active_ticker_count"),
        F.sum("portfolio_count").alias("portfolio_memberships"),
        F.max("latest_holding_update_ts").alias("latest_holding_update_ts"),
    )
)
