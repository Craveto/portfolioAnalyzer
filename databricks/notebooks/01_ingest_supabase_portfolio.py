# Databricks notebook source
# Step 2: Read holdings from Supabase Postgres into Bronze.

from pyspark.sql import functions as F


# COMMAND ----------
# Widgets / parameters

dbutils.widgets.text("jdbc_host", "your-supabase-host.pooler.supabase.com")
dbutils.widgets.text("jdbc_port", "5432")
dbutils.widgets.text("jdbc_database", "postgres")
dbutils.widgets.text("jdbc_user", "your-db-user")
dbutils.widgets.text("jdbc_password", "Bizzmetric@snehal")
dbutils.widgets.text("jdbc_schema", "public")
dbutils.widgets.text("source_tag", "supabase_postgres")
dbutils.widgets.text("batch_id", "")

jdbc_host = dbutils.widgets.get("jdbc_host")
jdbc_port = dbutils.widgets.get("jdbc_port")
jdbc_database = dbutils.widgets.get("jdbc_database")
jdbc_user = dbutils.widgets.get("jdbc_user")
jdbc_password = dbutils.widgets.get("jdbc_password")
jdbc_schema = dbutils.widgets.get("jdbc_schema")
source_tag = dbutils.widgets.get("source_tag") or "supabase_postgres"
batch_id = dbutils.widgets.get("batch_id")

if not batch_id:
    batch_id = spark.sql("SELECT replace(uuid(), '-', '') AS id").first()["id"]

jdbc_url = f"jdbc:postgresql://{jdbc_host}:{jdbc_port}/{jdbc_database}"


# COMMAND ----------
# Source query
#
# This query maps the current Django/Supabase schema:
# - auth_user
# - portfolio_portfolio
# - portfolio_holding
# - portfolio_stock
# - portfolio_sector

source_query = f"""
(
  SELECT
    CAST(p.user_id AS TEXT) AS user_id,
    CAST(h.portfolio_id AS TEXT) AS portfolio_id,
    UPPER(COALESCE(s.symbol, '')) AS ticker,
    CAST(h.qty AS DOUBLE PRECISION) AS quantity,
    CAST(h.avg_buy_price AS DOUBLE PRECISION) AS avg_buy_price,
    COALESCE(sec.name, s.name, 'Unknown') AS sector,
    h.updated_at AS updated_at
  FROM {jdbc_schema}.portfolio_holding h
  INNER JOIN {jdbc_schema}.portfolio_portfolio p
    ON p.id = h.portfolio_id
  INNER JOIN {jdbc_schema}.portfolio_stock s
    ON s.id = h.stock_id
  LEFT JOIN {jdbc_schema}.portfolio_sector sec
    ON sec.id = s.sector_id
  INNER JOIN {jdbc_schema}.auth_user u
    ON u.id = p.user_id
) AS holdings_src
"""


# COMMAND ----------
# Load from Supabase Postgres via JDBC

raw_df = (
    spark.read.format("jdbc")
    .option("url", jdbc_url)
    .option("dbtable", source_query)
    .option("user", jdbc_user)
    .option("password", jdbc_password)
    .option("driver", "org.postgresql.Driver")
    .load()
)


# COMMAND ----------
# Add Bronze ingestion metadata only.
# Do not over-transform in Bronze.

bronze_df = (
    raw_df.withColumn("batch_id", F.lit(batch_id))
    .withColumn("source_tag", F.lit(source_tag))
    .withColumn("ingestion_ts", F.current_timestamp())
    .select(
        "batch_id",
        "source_tag",
        "ingestion_ts",
        "user_id",
        "portfolio_id",
        "ticker",
        "quantity",
        "avg_buy_price",
        "sector",
        "updated_at",
    )
)


# COMMAND ----------
# Write to Bronze

(
    bronze_df.write.mode("append")
    .format("delta")
    .saveAsTable("portfolio_analyzer.bronze.bronze_portfolio_snapshot")
)


# COMMAND ----------
# Quick validation

display(bronze_df.limit(20))
display(
    spark.sql(
        """
        SELECT
          COUNT(*) AS row_count,
          COUNT(DISTINCT ticker) AS distinct_tickers,
          COUNT(DISTINCT portfolio_id) AS distinct_portfolios,
          MAX(ingestion_ts) AS latest_ingestion_ts
        FROM portfolio_analyzer.bronze.bronze_portfolio_snapshot
        WHERE batch_id = '{batch_id}'
        """.replace("{batch_id}", batch_id)
    )
)
