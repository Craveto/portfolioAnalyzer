# Databricks notebook source
# Step 2B: Validate Bronze holdings ingestion and prepare for downstream use.

from pyspark.sql import functions as F


# COMMAND ----------
# Bronze quality checks

bronze_df = spark.table("portfolio_analyzer.bronze.bronze_portfolio_snapshot")

display(bronze_df.limit(20))


# COMMAND ----------
# Null / invalid checks

quality_df = bronze_df.select(
    F.count("*").alias("row_count"),
    F.sum(F.when(F.col("user_id").isNull(), 1).otherwise(0)).alias("null_user_id"),
    F.sum(F.when(F.col("portfolio_id").isNull(), 1).otherwise(0)).alias("null_portfolio_id"),
    F.sum(F.when(F.col("ticker").isNull() | (F.trim(F.col("ticker")) == ""), 1).otherwise(0)).alias("null_or_blank_ticker"),
    F.sum(F.when(F.col("quantity").isNull(), 1).otherwise(0)).alias("null_quantity"),
    F.sum(F.when(F.col("avg_buy_price").isNull(), 1).otherwise(0)).alias("null_avg_buy_price"),
    F.sum(F.when(F.col("updated_at").isNull(), 1).otherwise(0)).alias("null_updated_at"),
    F.sum(F.when(F.col("quantity") <= 0, 1).otherwise(0)).alias("non_positive_quantity"),
)

display(quality_df)


# COMMAND ----------
# Batch-level profile

batch_profile_df = (
    bronze_df.groupBy("batch_id", "source_tag")
    .agg(
        F.count("*").alias("row_count"),
        F.countDistinct("portfolio_id").alias("portfolio_count"),
        F.countDistinct("ticker").alias("ticker_count"),
        F.max("ingestion_ts").alias("latest_ingestion_ts"),
        F.max("updated_at").alias("latest_source_update_ts"),
    )
    .orderBy(F.col("latest_ingestion_ts").desc())
)

display(batch_profile_df)


# COMMAND ----------
# Readiness view for downstream steps
#
# This is still Bronze-derived and does not replace Silver cleaning.

readiness_df = (
    bronze_df.filter(F.col("ticker").isNotNull())
    .filter(F.trim(F.col("ticker")) != "")
    .filter(F.col("quantity").isNotNull())
    .filter(F.col("quantity") > 0)
)

display(
    readiness_df.select("portfolio_id", "ticker", "quantity", "avg_buy_price", "updated_at")
    .orderBy("portfolio_id", "ticker")
)
