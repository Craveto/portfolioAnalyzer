# Databricks notebook source
# Step 8/9: Score clean news with FinBERT and normalize outputs.

from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StringType, StructField, StructType
import re


# COMMAND ----------
# Optional package install when running interactively in Databricks
# %pip install transformers torch


# COMMAND ----------
# Read clean Silver news

silver_news_df = spark.table("portfolio_analyzer.silver.silver_news_clean")


# COMMAND ----------
# Event type and impact helpers

EVENT_PATTERNS = {
    "earnings": ["earnings", "results", "revenue", "profit", "q1", "q2", "q3", "q4"],
    "analyst_rating": ["upgrade", "downgrade", "rating", "brokerage", "target price"],
    "guidance": ["guidance", "outlook", "forecast", "margin"],
    "legal": ["lawsuit", "court", "penalty", "probe", "regulator", "compliance"],
    "product": ["launch", "contract", "order", "deal", "product", "platform"],
    "management": ["ceo", "cfo", "management", "board", "resigns", "appoints"],
    "macro": ["inflation", "rates", "economy", "usd", "rupee", "oil"],
    "merger_acquisition": ["merger", "acquisition", "buyout", "stake"],
    "dividend": ["dividend", "buyback", "bonus", "payout"],
}


def detect_event_type(text: str) -> str:
    lowered = (text or "").lower()
    for event_type, keywords in EVENT_PATTERNS.items():
        if any(keyword in lowered for keyword in keywords):
            return event_type
    return "other"


def detect_impact_level(event_type: str, confidence_score: float, normalized_score: int) -> str:
    if event_type in {"earnings", "legal", "guidance", "merger_acquisition"}:
        return "high"
    if abs(normalized_score) == 1 and confidence_score >= 0.8:
        return "high"
    if event_type in {"analyst_rating", "management", "macro", "product"} or confidence_score >= 0.55:
        return "medium"
    return "low"


def compute_relevance_score(ticker: str, headline: str, summary: str) -> float:
    base_ticker = ((ticker or "").split(".")[0]).lower()
    text = f"{headline or ''} {summary or ''}".lower()
    score = 0.4
    if base_ticker and base_ticker in text:
        score += 0.35
    if len(text.strip()) > 80:
        score += 0.15
    return round(min(score, 1.0), 2)


# COMMAND ----------
# FinBERT scoring setup

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

    finbert_pipe = pipeline(
        "text-classification",
        model="ProsusAI/finbert",
        tokenizer="ProsusAI/finbert",
        truncation=True,
        max_length=256,
    )
except Exception:
    finbert_pipe = None


def fallback_sentiment(text: str) -> tuple[str, float, int]:
    lowered = (text or "").lower()
    positive_terms = ["beat", "growth", "strong", "upgrade", "profit", "surge", "order", "approval"]
    negative_terms = ["miss", "weak", "downgrade", "lawsuit", "risk", "warning", "loss", "pressure"]
    pos_hits = sum(1 for term in positive_terms if term in lowered)
    neg_hits = sum(1 for term in negative_terms if term in lowered)
    if pos_hits > neg_hits:
        return "positive", 0.62, 1
    if neg_hits > pos_hits:
        return "negative", 0.62, -1
    return "neutral", 0.5, 0


def normalize_finbert_label(label: str) -> tuple[str, int]:
    lowered = (label or "").lower()
    if lowered == "positive":
        return "positive", 1
    if lowered == "negative":
        return "negative", -1
    return "neutral", 0


def score_article(ticker: str, headline: str, summary: str):
    text = re.sub(r"\s+", " ", f"{headline or ''}. {summary or ''}").strip()
    if not text:
        sentiment_label, confidence_score, normalized_score = "neutral", 0.5, 0
    elif finbert_pipe is not None:
        result = finbert_pipe(text[:400])[0]
        sentiment_label, normalized_score = normalize_finbert_label(result.get("label"))
        confidence_score = float(result.get("score") or 0.5)
    else:
        sentiment_label, confidence_score, normalized_score = fallback_sentiment(text)

    relevance_score = compute_relevance_score(ticker, headline, summary)
    event_type = detect_event_type(text)
    impact_level = detect_impact_level(event_type, confidence_score, normalized_score)
    return (
        sentiment_label,
        round(float(confidence_score), 4),
        int(normalized_score),
        float(relevance_score),
        impact_level,
        event_type,
    )


score_schema = StructType(
    [
        StructField("sentiment_label", StringType(), True),
        StructField("confidence_score", DoubleType(), True),
        StructField("normalized_score", IntegerType(), True),
        StructField("relevance_score", DoubleType(), True),
        StructField("impact_level", StringType(), True),
        StructField("event_type", StringType(), True),
    ]
)

score_udf = F.udf(score_article, score_schema)


# COMMAND ----------
# Score and normalize output

scored_df = (
    silver_news_df.withColumn(
        "score_struct",
        score_udf("ticker", "headline", "summary"),
    )
    .select(
        "ticker",
        "source",
        "headline",
        "url",
        "published_at",
        F.col("score_struct.sentiment_label").alias("sentiment_label"),
        F.col("score_struct.confidence_score").alias("confidence_score"),
        F.col("score_struct.normalized_score").alias("normalized_score"),
        F.col("score_struct.relevance_score").alias("relevance_score"),
        F.col("score_struct.impact_level").alias("impact_level"),
        F.col("score_struct.event_type").alias("event_type"),
        F.current_timestamp().alias("scored_ts"),
    )
)


# COMMAND ----------
# Write to Silver scored table

(
    scored_df.write.mode("overwrite")
    .format("delta")
    .saveAsTable("portfolio_analyzer.silver.silver_news_scored")
)


# COMMAND ----------
# Validation outputs

display(scored_df.limit(20))

display(
    scored_df.groupBy("sentiment_label")
    .agg(
        F.count("*").alias("row_count"),
        F.avg("confidence_score").alias("avg_confidence"),
    )
    .orderBy("sentiment_label")
)

display(
    scored_df.groupBy("ticker")
    .agg(
        F.count("*").alias("article_count"),
        F.sum(F.when(F.col("impact_level") == "high", 1).otherwise(0)).alias("high_impact_count"),
    )
    .orderBy("ticker")
)
