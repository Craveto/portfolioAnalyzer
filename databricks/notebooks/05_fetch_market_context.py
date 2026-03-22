# Databricks notebook source
# Step 5: Fetch market/fundamental context for active tickers into Bronze using yfinance only.

import json
from pyspark.sql import Row
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, TimestampType, DoubleType

dbutils.widgets.removeAll()

try:
    import yfinance as yf
except Exception:
    yf = None

dbutils.widgets.text("source_tag", "yfinance_market_context")
dbutils.widgets.text("batch_id", "")
dbutils.widgets.text("max_tickers", "10")

source_tag = dbutils.widgets.get("source_tag") or "yfinance_market_context"
batch_id = dbutils.widgets.get("batch_id")
max_tickers = int(dbutils.widgets.get("max_tickers") or "10")

if not batch_id:
    batch_id = spark.sql("SELECT replace(uuid(), '-', '') AS id").first()["id"]

if yf is None:
    raise ValueError("yfinance is not available on this cluster. Install it first with %pip install yfinance")

def to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

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

def fetch_yfinance_context(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    fast_info = getattr(t, "fast_info", None) or {}
    info = {}

    try:
        get_info = getattr(t, "get_info", None)
        if callable(get_info):
            info = get_info() or {}
        else:
            info = getattr(t, "info", None) or {}
    except Exception:
        info = {}

    last_price = to_float(fast_info.get("last_price") or info.get("currentPrice") or info.get("regularMarketPrice"))
    previous_close = to_float(fast_info.get("previous_close") or info.get("previousClose"))
    pe_ratio = to_float(info.get("trailingPE") or info.get("forwardPE"))
    market_cap = to_float(info.get("marketCap"))

    earnings_context = None
    earnings_date = info.get("earningsTimestamp") or info.get("earningsDate")
    if earnings_date:
        earnings_context = str(earnings_date)

    return {
        "ticker": ticker,
        "last_price": last_price,
        "previous_close": previous_close,
        "pe_ratio": pe_ratio,
        "market_cap": market_cap,
        "earnings_context": earnings_context,
        "raw": {
            "fast_info": dict(fast_info) if hasattr(fast_info, "keys") else str(fast_info),
            "info": info,
        },
    }

rows = []
fetch_ts = spark.sql("SELECT current_timestamp() AS ts").first()["ts"]

for ticker in active_tickers:
    try:
        payload = fetch_yfinance_context(ticker)
        last_price = payload.get("last_price")
        previous_close = payload.get("previous_close")
        pe_ratio = payload.get("pe_ratio")
        market_cap = payload.get("market_cap")
        earnings_context = payload.get("earnings_context")

        daily_change_pct = None
        if previous_close not in (None, 0.0) and last_price is not None:
            daily_change_pct = to_float(((last_price - previous_close) / previous_close) * 100.0)

        print("ticker =", ticker, "last_price =", last_price, "market_cap =", market_cap)

        rows.append(
            Row(
                batch_id=str(batch_id),
                source_tag=f"{source_tag}:success",
                ingestion_ts=fetch_ts,
                ticker=str(ticker),
                last_price=last_price,
                daily_change_pct=daily_change_pct,
                pe_ratio=pe_ratio,
                market_cap=market_cap,
                earnings_context=earnings_context,
                raw_json=safe_json(payload.get("raw")),
                fetch_ts=fetch_ts,
            )
        )

    except Exception as exc:
        rows.append(
            Row(
                batch_id=str(batch_id),
                source_tag=f"{source_tag}:error",
                ingestion_ts=fetch_ts,
                ticker=str(ticker),
                last_price=None,
                daily_change_pct=None,
                pe_ratio=None,
                market_cap=None,
                earnings_context=None,
                raw_json=safe_json({"ticker": ticker, "error": str(exc)}),
                fetch_ts=fetch_ts,
            )
        )

market_schema = StructType([
    StructField("batch_id", StringType(), True),
    StructField("source_tag", StringType(), True),
    StructField("ingestion_ts", TimestampType(), True),
    StructField("ticker", StringType(), True),
    StructField("last_price", DoubleType(), True),
    StructField("daily_change_pct", DoubleType(), True),
    StructField("pe_ratio", DoubleType(), True),
    StructField("market_cap", DoubleType(), True),
    StructField("earnings_context", StringType(), True),
    StructField("raw_json", StringType(), True),
    StructField("fetch_ts", TimestampType(), True),
])

market_df = spark.createDataFrame(rows, schema=market_schema)

(
    market_df.write.mode("append")
    .format("delta")
    .saveAsTable("portfolio_analyzer.bronze.bronze_market_data_raw")
)

display(market_df)
display(
    market_df.groupBy("ticker")
    .agg(
        F.count("*").alias("rows_written"),
        F.max("last_price").alias("last_price"),
        F.max("daily_change_pct").alias("daily_change_pct"),
        F.max("pe_ratio").alias("pe_ratio"),
        F.max("market_cap").alias("market_cap"),
    )
    .orderBy("ticker")
)

