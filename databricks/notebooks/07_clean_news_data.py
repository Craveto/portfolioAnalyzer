# Databricks notebook source
# Step 7: Clean raw news into Silver.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Bronze raw news

bronze_news_df = spark.table("portfolio_analyzer.bronze.bronze_news_raw")
# Databricks notebook source
# Step 7: Clean raw news into Silver.

from pyspark.sql import Window
from pyspark.sql import functions as F


# COMMAND ----------
# Read Bronze raw news

bronze_news_df = spark.table("portfolio_analyzer.bronze.bronze_news_raw")


# COMMAND ----------
# Normalize and clean text fields

clean_df = (
    bronze_news_df.withColumn("ticker", F.upper(F.trim(F.col("ticker"))))
    .withColumn("source", F.trim(F.col("source")))
    .withColumn("headline", F.regexp_replace(F.col("headline"), "<[^>]+>", " "))
    .withColumn("summary", F.regexp_replace(F.col("summary"), "<[^>]+>", " "))
    .withColumn("headline", F.trim(F.regexp_replace(F.col("headline"), r"\s+", " ")))
    .withColumn("summary", F.trim(F.regexp_replace(F.col("summary"), r"\s+", " ")))
    .withColumn("url", F.trim(F.col("url")))
    .withColumn("published_at", F.col("published_at").cast("timestamp"))
)


# COMMAND ----------
# Basic relevance filtering
#
# Keep rows only if:
# - ticker exists
# - headline exists
# - headline length is meaningful

filtered_df = (
    clean_df.filter(F.col("ticker").isNotNull())
    .filter(F.trim(F.col("ticker")) != "")
    .filter(F.col("headline").isNotNull())
    .filter(F.trim(F.col("headline")) != "")
    .filter(F.length(F.col("headline")) >= 12)
)


# COMMAND ----------
# Content hash for deduplication

hashed_df = filtered_df.withColumn(
    "content_hash",
    F.sha2(
        F.concat_ws(
            "||",
            F.col("ticker"),
            F.coalesce(F.col("headline"), F.lit("")),
            F.coalesce(F.col("source"), F.lit("")),
            F.coalesce(F.col("url"), F.lit("")),
        ),
        256,
    ),
)


# COMMAND ----------
# Deduplicate and keep the latest version of each article shape

dedupe_window = Window.partitionBy("content_hash").orderBy(
    F.col("published_at").desc_nulls_last(),
    F.col("ingestion_ts").desc_nulls_last(),
)

deduped_df = (
    hashed_df.withColumn("rn", F.row_number().over(dedupe_window))
    .filter(F.col("rn") == 1)
    .drop("rn")
)


# COMMAND ----------
# Relevance flag
#
# For now this is a simple, explainable rule:
# headline or summary should mention the base ticker symbol,
# or the row should at least have a non-empty headline tied to the fetched ticker.

base_ticker_col = F.split(F.col("ticker"), r"\.").getItem(0)

relevance_df = deduped_df.withColumn(
    "relevance_flag",
    F.when(
        F.lower(F.concat_ws(" ", F.coalesce(F.col("headline"), F.lit("")), F.coalesce(F.col("summary"), F.lit("")))).contains(F.lower(base_ticker_col)),
        F.lit(True),
    ).otherwise(F.lit(True)),
)


# COMMAND ----------
# Final Silver projection

silver_news_clean_df = relevance_df.select(
    "ticker",
    "source",
    "headline",
    "summary",
    "url",
    "published_at",
    "content_hash",
    "relevance_flag",
    F.current_timestamp().alias("cleaned_ts"),
)


# COMMAND ----------
# Write to Silver

(
    silver_news_clean_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_news_clean")
)


# COMMAND ----------
# Validation outputs

display(silver_news_clean_df.limit(20))

display(
    silver_news_clean_df.agg(
        F.count("*").alias("clean_news_rows"),
        F.countDistinct("ticker").alias("ticker_count"),
        F.countDistinct("content_hash").alias("distinct_articles"),
        F.sum(F.when(F.col("relevance_flag") == True, 1).otherwise(0)).alias("relevant_rows"),
    )
)

display(
    silver_news_clean_df.groupBy("ticker")
    .agg(
        F.count("*").alias("article_count"),
        F.max("published_at").alias("latest_article_ts"),
    )
    .orderBy("ticker")
)


# COMMAND ----------
# Normalize and clean text fields

clean_df = (
    bronze_news_df.withColumn("ticker", F.upper(F.trim(F.col("ticker"))))
    .withColumn("source", F.trim(F.col("source")))
    .withColumn("headline", F.regexp_replace(F.col("headline"), "<[^>]+>", " "))
    .withColumn("summary", F.regexp_replace(F.col("summary"), "<[^>]+>", " "))
    .withColumn("headline", F.trim(F.regexp_replace(F.col("headline"), r"\s+", " ")))
    .withColumn("summary", F.trim(F.regexp_replace(F.col("summary"), r"\s+", " ")))
    .withColumn("url", F.trim(F.col("url")))
    .withColumn("published_at", F.col("published_at").cast("timestamp"))
)


# COMMAND ----------
# Basic relevance filtering
#
# Keep rows only if:
# - ticker exists
# - headline exists
# - headline length is meaningful

filtered_df = (
    clean_df.filter(F.col("ticker").isNotNull())
    .filter(F.trim(F.col("ticker")) != "")
    .filter(F.col("headline").isNotNull())
    .filter(F.trim(F.col("headline")) != "")
    .filter(F.length(F.col("headline")) >= 12)
)


# COMMAND ----------
# Content hash for deduplication

hashed_df = filtered_df.withColumn(
    "content_hash",
    F.sha2(
        F.concat_ws(
            "||",
            F.col("ticker"),
            F.coalesce(F.col("headline"), F.lit("")),
            F.coalesce(F.col("source"), F.lit("")),
            F.coalesce(F.col("url"), F.lit("")),
        ),
        256,
    ),
)


# COMMAND ----------
# Deduplicate and keep the latest version of each article shape

dedupe_window = Window.partitionBy("content_hash").orderBy(
    F.col("published_at").desc_nulls_last(),
    F.col("ingestion_ts").desc_nulls_last(),
)

deduped_df = (
    hashed_df.withColumn("rn", F.row_number().over(dedupe_window))
    .filter(F.col("rn") == 1)
    .drop("rn")
)


# COMMAND ----------
# Relevance flag
#
# For now this is a simple, explainable rule:
# headline or summary should mention the base ticker symbol,
# or the row should at least have a non-empty headline tied to the fetched ticker.

base_ticker_col = F.split(F.col("ticker"), r"\.").getItem(0)

relevance_df = deduped_df.withColumn(
    "relevance_flag",
    F.when(
        F.lower(F.concat_ws(" ", F.coalesce(F.col("headline"), F.lit("")), F.coalesce(F.col("summary"), F.lit("")))).contains(F.lower(base_ticker_col)),
        F.lit(True),
    ).otherwise(F.lit(True)),
)


# COMMAND ----------
# Final Silver projection

silver_news_clean_df = relevance_df.select(
    "ticker",
    "source",
    "headline",
    "summary",
    "url",
    "published_at",
    "content_hash",
    "relevance_flag",
    F.current_timestamp().alias("cleaned_ts"),
)


# COMMAND ----------
# Write to Silver

(
    silver_news_clean_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_news_clean")
)


# COMMAND ----------
# Validation outputs

display(silver_news_clean_df.limit(20))

display(
    silver_news_clean_df.agg(
        F.count("*").alias("clean_news_rows"),
        F.countDistinct("ticker").alias("ticker_count"),
        F.countDistinct("content_hash").alias("distinct_articles"),
        F.sum(F.when(F.col("relevance_flag") == True, 1).otherwise(0)).alias("relevant_rows"),
    )
)

display(
    silver_news_clean_df.groupBy("ticker")
    .agg(
        F.count("*").alias("article_count"),
        F.max("published_at").alias("latest_article_ts"),
    )
    .orderBy("ticker")
)
