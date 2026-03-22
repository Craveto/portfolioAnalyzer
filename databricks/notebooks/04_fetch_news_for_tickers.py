# Databricks notebook source
# Step 4: Fetch raw news for active tickers into Bronze using yfinance only.

import json
from pyspark.sql import Row
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, TimestampType

dbutils.widgets.removeAll()

try:
    import yfinance as yf
except Exception:
    yf = None

dbutils.widgets.text("source_tag", "yfinance_news")
dbutils.widgets.text("batch_id", "")
dbutils.widgets.text("max_tickers", "10")

source_tag = dbutils.widgets.get("source_tag") or "yfinance_news"
batch_id = dbutils.widgets.get("batch_id")
max_tickers = int(dbutils.widgets.get("max_tickers") or "10")

if not batch_id:
    batch_id = spark.sql("SELECT replace(uuid(), '-', '') AS id").first()["id"]

if yf is None:
    raise ValueError("yfinance is not available on this cluster. Install it first with %pip install yfinance")

def safe_json(payload):
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return json.dumps({"error": "json_serialize_failed"})

active_tickers = [
    row["ticker"]
    for row in (
        spark.table("portfolio_analyzer.silver.silver_active_ticker_list")
        .orderBy("ticker")
        .limit(max_tickers)
        .collect()
    )
]

if not active_tickers:
    raise ValueError("No active tickers found in silver_active_ticker_list. Run Step 3 first.")

def fetch_yfinance_news(ticker: str) -> list[dict]:
    try:
        items = getattr(yf.Ticker(ticker), "news", None) or []
    except Exception:
        return []

    out = []

    for item in items:
        content = item.get("content") or {}
        canonical_url = content.get("canonicalUrl") or {}
        provider = item.get("publisher") or content.get("provider") or "yfinance"

        headline = (
            item.get("title")
            or content.get("title")
            or item.get("headline")
        )

        summary = (
            item.get("summary")
            or content.get("summary")
            or content.get("description")
        )

        url = (
            item.get("link")
            or item.get("url")
            or canonical_url.get("url")
        )

        published_at = (
            item.get("providerPublishTime")
            or item.get("pubDate")
            or content.get("pubDate")
        )

        out.append(
            {
                "source": provider,
                "headline": headline,
                "summary": summary,
                "url": url,
                "published_at": published_at,
                "raw": item,
            }
        )

    return out

rows = []
fetch_ts = spark.sql("SELECT current_timestamp() AS ts").first()["ts"]

for ticker in active_tickers:
    try:
        payload = fetch_yfinance_news(ticker)
        print("ticker =", ticker, "payload_count =", len(payload))

        if not payload:
            rows.append(
                Row(
                    batch_id=str(batch_id),
                    source_tag=f"{source_tag}:empty",
                    ingestion_ts=fetch_ts,
                    ticker=str(ticker),
                    source="none",
                    headline=None,
                    summary=None,
                    url=None,
                    published_at=None,
                    raw_json=safe_json({"ticker": ticker, "message": "no_news_found"}),
                    fetch_ts=fetch_ts,
                )
            )
            continue
        
        for item in payload:
           headline = item.get("headline")
           summary = item.get("summary")
           url = item.get("url")
           published_at = item.get("published_at")

           if not headline and not summary and not url:
               continue

           rows.append(
               Row(
                  batch_id=str(batch_id),
                  source_tag=f"{source_tag}:success",
                  ingestion_ts=fetch_ts,
                  ticker=str(ticker),
                  source=item.get("source") or "yfinance",
                  headline=headline,
                  summary=summary,
                  url=url,
                  published_at=str(published_at) if published_at is not None else None,
                  raw_json=safe_json(item.get("raw") or item),
                  fetch_ts=fetch_ts,
                )
            )

        # for item in payload:
        #     rows.append(
        #         Row(
        #             batch_id=str(batch_id),
        #             source_tag=f"{source_tag}:success",
        #             ingestion_ts=fetch_ts,
        #             ticker=str(ticker),
        #             source=item.get("source") or "yfinance",
        #             headline=item.get("headline"),
        #             summary=item.get("summary"),
        #             url=item.get("url"),
        #             published_at=str(item.get("published_at")) if item.get("published_at") is not None else None,
        #             raw_json=safe_json(item.get("raw") or item),
        #             fetch_ts=fetch_ts,
        #         )
        #     )

    except Exception as exc:
        rows.append(
            Row(
                batch_id=str(batch_id),
                source_tag=f"{source_tag}:error",
                ingestion_ts=fetch_ts,
                ticker=str(ticker),
                source="error",
                headline=None,
                summary=None,
                url=None,
                published_at=None,
                raw_json=safe_json({"ticker": ticker, "error": str(exc)}),
                fetch_ts=fetch_ts,
            )
        )

news_schema = StructType([
    StructField("batch_id", StringType(), True),
    StructField("source_tag", StringType(), True),
    StructField("ingestion_ts", TimestampType(), True),
    StructField("ticker", StringType(), True),
    StructField("source", StringType(), True),
    StructField("headline", StringType(), True),
    StructField("summary", StringType(), True),
    StructField("url", StringType(), True),
    StructField("published_at", StringType(), True),
    StructField("raw_json", StringType(), True),
    StructField("fetch_ts", TimestampType(), True),
])

news_df = spark.createDataFrame(rows, schema=news_schema)

news_df = (
    news_df.withColumn(
        "published_at",
        F.when(
            F.col("published_at").rlike("^[0-9]+$"),
            F.to_timestamp(F.from_unixtime(F.col("published_at").cast("long")))
        ).otherwise(
            F.coalesce(
                F.to_timestamp(F.col("published_at")),
                F.to_timestamp(F.col("published_at"), "yyyy-MM-dd'T'HH:mm:ss'Z'"),
                F.to_timestamp(F.col("published_at"), "EEE, dd MMM yyyy HH:mm:ss z")
            )
        )
    )
    .select(
        "batch_id",
        "source_tag",
        "ingestion_ts",
        "ticker",
        "source",
        "headline",
        "summary",
        "url",
        "published_at",
        "raw_json",
        "fetch_ts",
    )
)


(
    news_df.write.mode("append")
    .format("delta")
    .saveAsTable("portfolio_analyzer.bronze.bronze_news_raw")
)

display(news_df.limit(50))
display(
    news_df.groupBy("ticker")
    .agg(
        F.count("*").alias("news_rows"),
        F.count(F.when(F.col("headline").isNotNull(), 1)).alias("headline_rows"),
        F.max("published_at").alias("latest_published_at"),
    )
    .orderBy("ticker")
)
