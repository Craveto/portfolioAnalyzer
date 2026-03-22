# Databricks notebook source
# Step 6: Clean holdings from Bronze into Silver.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Bronze holdings snapshot

bronze_df = spark.table("portfolio_analyzer.bronze.bronze_portfolio_snapshot")


# COMMAND ----------
# Normalize raw fields

normalized_df = (
    bronze_df.withColumn("user_id", F.trim(F.col("user_id")))
    .withColumn("portfolio_id", F.trim(F.col("portfolio_id")))
    .withColumn("ticker", F.upper(F.trim(F.col("ticker"))))
    .withColumn("sector", F.initcap(F.trim(F.col("sector"))))
    .withColumn("quantity", F.col("quantity").cast("double"))
    .withColumn("avg_buy_price", F.col("avg_buy_price").cast("double"))
)


# COMMAND ----------
# Basic validation rules
#
# Keep rows only if:
# - user_id and portfolio_id are present
# - ticker exists
# - quantity is positive
# - avg_buy_price is non-negative

validated_df = (
    normalized_df.filter(F.col("user_id").isNotNull())
    .filter(F.trim(F.col("user_id")) != "")
    .filter(F.col("portfolio_id").isNotNull())
    .filter(F.trim(F.col("portfolio_id")) != "")
    .filter(F.col("ticker").isNotNull())
    .filter(F.trim(F.col("ticker")) != "")
    .filter(F.col("quantity").isNotNull())
    .filter(F.col("quantity") > 0)
    .filter(F.col("avg_buy_price").isNotNull())
    .filter(F.col("avg_buy_price") >= 0)
)


# COMMAND ----------
# Standardize missing or noisy sectors

cleaned_df = validated_df.withColumn(
    "sector",
    F.when(F.col("sector").isNull() | (F.trim(F.col("sector")) == ""), F.lit("Unknown")).otherwise(F.col("sector")),
)


# COMMAND ----------
# Keep the latest holding state per user/portfolio/ticker

latest_window = Window.partitionBy("user_id", "portfolio_id", "ticker").orderBy(
    F.col("updated_at").desc_nulls_last(),
    F.col("ingestion_ts").desc_nulls_last(),
)

latest_clean_df = (
    cleaned_df.withColumn("rn", F.row_number().over(latest_window))
    .filter(F.col("rn") == 1)
    .drop("rn")
    .select(
        "user_id",
        "portfolio_id",
        "ticker",
        "quantity",
        "avg_buy_price",
        "sector",
        "updated_at",
        F.current_timestamp().alias("as_of_ts"),
    )
)


# COMMAND ----------
# Write to Silver

(
    latest_clean_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_portfolio_clean")
)


# COMMAND ----------
# Validation outputs

display(latest_clean_df.limit(20))

display(
    latest_clean_df.agg(
        F.count("*").alias("clean_row_count"),
        F.countDistinct("portfolio_id").alias("portfolio_count"),
        F.countDistinct("ticker").alias("ticker_count"),
        F.sum(F.when(F.col("sector") == "Unknown", 1).otherwise(0)).alias("unknown_sector_rows"),
    )
)

display(
    latest_clean_df.groupBy("ticker")
    .agg(
        F.countDistinct("portfolio_id").alias("portfolio_count"),
        F.sum("quantity").alias("total_quantity"),
        F.avg("avg_buy_price").alias("avg_buy_price"),
    )
    .orderBy("ticker")
)
