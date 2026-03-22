from __future__ import annotations

import ast
import os

from portfolio.models import Portfolio

from api.yf_client import get_52w_range, get_fast_quote, get_fundamentals

from .databricks_client import fetch_all, fetch_one, parse_json_field


def _portfolio_scope(portfolio: Portfolio) -> tuple[str, str]:
    return str(portfolio.user_id), str(portfolio.id)


def _clean_headline(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and "displayName" in text:
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, dict) and parsed.get("displayName"):
                    return str(parsed.get("displayName"))
            except Exception:
                return text
        return text
    return str(value)


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def get_portfolio_sentiment_from_databricks(portfolio: Portfolio) -> dict:
    user_id, portfolio_id = _portfolio_scope(portfolio)

    summary_row = fetch_one(
        """
        SELECT
          user_id,
          portfolio_id,
          portfolio_sentiment,
          portfolio_sentiment_score,
          most_positive_stock,
          most_risky_stock,
          most_mentioned_stock,
          sector_sentiment_mix,
          as_of_ts
        FROM portfolio_analyzer.gold.gold_portfolio_summary
        WHERE user_id = ? AND portfolio_id = ?
        ORDER BY as_of_ts DESC
        LIMIT 1
        """,
        [user_id, portfolio_id],
    )

    stock_rows = fetch_all(
        """
        SELECT
          spc.ticker AS symbol,
          gsi.sentiment_score_7d AS sentiment_score,
          gsi.news_count,
          gsi.high_impact_news_count,
          CASE
            WHEN gsi.sentiment_score_7d >= 1.0 THEN 'Bullish'
            WHEN gsi.sentiment_score_7d <= -1.0 THEN 'Bearish'
            ELSE 'Neutral'
          END AS signal,
          spc.sector
        FROM portfolio_analyzer.silver.silver_portfolio_clean spc
        LEFT JOIN portfolio_analyzer.gold.gold_stock_insight_current gsi
          ON gsi.ticker = spc.ticker
        WHERE spc.user_id = ? AND spc.portfolio_id = ?
        ORDER BY spc.ticker
        """,
        [user_id, portfolio_id],
    )

    normalized_rows = []
    for row in stock_rows:
        score = row.get("sentiment_score")
        mentions = row.get("news_count")
        high_impact = row.get("high_impact_news_count")
        try:
            score = float(score) if score is not None else 0.0
        except Exception:
            score = 0.0
        try:
            mentions = int(mentions) if mentions is not None else 0
        except Exception:
            mentions = 0
        try:
            high_impact = int(high_impact) if high_impact is not None else 0
        except Exception:
            high_impact = 0

        out = dict(row)
        out["sentiment_score"] = score
        out["news_count"] = mentions
        out["high_impact_news_count"] = high_impact
        out["risk_flags"] = ([f"{high_impact} high-impact headlines"] if high_impact > 0 else [])
        normalized_rows.append(out)

    def _pick_distinct() -> tuple[dict | None, dict | None, dict | None]:
        if not normalized_rows:
            return None, None, None

        by_symbol = {str(r.get("symbol")): r for r in normalized_rows if r.get("symbol")}
        used_symbols: set[str] = set()

        def _best(sort_key, reverse: bool = True):
            for item in sorted(normalized_rows, key=sort_key, reverse=reverse):
                symbol = item.get("symbol")
                if symbol and symbol not in used_symbols:
                    used_symbols.add(symbol)
                    return item
            return None

        def _summary_pick(symbol_key: str):
            symbol = summary_row.get(symbol_key) if summary_row else None
            if not symbol:
                return None
            item = by_symbol.get(str(symbol))
            if not item:
                return None
            if item.get("symbol") in used_symbols:
                return None
            used_symbols.add(item.get("symbol"))
            return item

        most_positive = _summary_pick("most_positive_stock") or _best(lambda r: (r.get("sentiment_score") or 0.0, r.get("news_count") or 0))
        most_risky = _summary_pick("most_risky_stock") or _best(lambda r: (r.get("high_impact_news_count") or 0, -(r.get("sentiment_score") or 0.0), r.get("news_count") or 0))
        most_mentioned = _summary_pick("most_mentioned_stock") or _best(lambda r: (r.get("news_count") or 0, r.get("high_impact_news_count") or 0))
        return most_positive, most_risky, most_mentioned

    if not summary_row:
        return {
            "portfolio": {"id": portfolio.id, "name": portfolio.name},
            "portfolio_summary": {
                "portfolio_signal": "Neutral",
                "portfolio_sentiment_score": 0.0,
                "most_positive_stock": None,
                "most_risky_stock": None,
                "most_mentioned_stock": None,
                "sector_sentiment_mix": [],
            },
            "stocks": normalized_rows,
            "meta": {"source": "databricks_gold", "provider": "databricks"},
        }
    most_positive_stock, most_risky_stock, most_mentioned_stock = _pick_distinct()

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "portfolio_summary": {
            "portfolio_signal": summary_row.get("portfolio_sentiment") or "Neutral",
            "portfolio_sentiment_score": summary_row.get("portfolio_sentiment_score") or 0.0,
            "most_positive_stock": most_positive_stock,
            "most_risky_stock": most_risky_stock,
            "most_mentioned_stock": most_mentioned_stock,
            "sector_sentiment_mix": parse_json_field(summary_row.get("sector_sentiment_mix")) or [],
            "as_of_ts": summary_row.get("as_of_ts"),
        },
        "stocks": normalized_rows,
        "meta": {
            "source": "databricks_gold",
            "provider": "databricks",
            "gold_table": "gold_portfolio_summary",
            "as_of_ts": summary_row.get("as_of_ts"),
        },
    }


def get_stock_insight_from_databricks(portfolio: Portfolio, symbol: str) -> dict:
    user_id, portfolio_id = _portfolio_scope(portfolio)
    symbol = symbol.upper()

    stock_row = fetch_one(
        """
        SELECT
          spc.ticker,
          spc.sector,
          spc.quantity,
          spc.avg_buy_price,
          gsi.sentiment_score_24h,
          gsi.sentiment_score_7d,
          gsi.news_count,
          gsi.positive_count,
          gsi.negative_count,
          gsi.neutral_count,
          gsi.high_impact_news_count,
          gsi.dominant_event_type,
          gsi.trend_direction,
          gsi.last_price,
          gsi.daily_change_pct,
          gsi.pe_ratio,
          gsi.market_cap,
          gsi.as_of_ts
        FROM portfolio_analyzer.silver.silver_portfolio_clean spc
        LEFT JOIN portfolio_analyzer.gold.gold_stock_insight_current gsi
          ON gsi.ticker = spc.ticker
        WHERE spc.user_id = ? AND spc.portfolio_id = ? AND spc.ticker = ?
        LIMIT 1
        """,
        [user_id, portfolio_id, symbol],
    )
    if not stock_row:
        raise Portfolio.DoesNotExist(f"Ticker {symbol} not found for portfolio {portfolio.id}")

    news_rows = fetch_all(
        """
        SELECT
          ticker,
          cleaned_headline,
          source,
          published_at,
          sentiment_label,
          impact_level,
          short_explanation_tag,
          url
        FROM portfolio_analyzer.gold.gold_stock_news_view
        WHERE ticker = ?
          AND published_at >= current_timestamp() - INTERVAL 1 DAY
        ORDER BY published_at DESC
        LIMIT 5
        """,
        [symbol],
    )
    if not news_rows:
        news_rows = fetch_all(
            """
            SELECT
              ticker,
              cleaned_headline,
              source,
              published_at,
              sentiment_label,
              impact_level,
              short_explanation_tag,
              url
            FROM portfolio_analyzer.gold.gold_stock_news_view
            WHERE ticker = ?
            ORDER BY published_at DESC
            LIMIT 5
            """,
            [symbol],
        )

    report_row = fetch_one(
        """
        SELECT
          top_news_json,
          risk_flags_json,
          market_context_json,
          executive_summary,
          sentiment_explanation,
          short_term_outlook,
          risk_assessment,
          verdict,
          as_of_ts
        FROM portfolio_analyzer.gold.gold_stock_report_dataset
        WHERE ticker = ?
        ORDER BY as_of_ts DESC
        LIMIT 1
        """,
        [symbol],
    ) or {}

    signal = "Bullish" if (stock_row.get("sentiment_score_7d") or 0) >= 1.0 else ("Bearish" if (stock_row.get("sentiment_score_7d") or 0) <= -1.0 else "Neutral")

    parsed_market_context = parse_json_field(report_row.get("market_context_json")) or {}
    if not isinstance(parsed_market_context, dict):
        parsed_market_context = {}

    # Normalize keys from Databricks report schema to frontend contract.
    market_context = {
        "last_price": parsed_market_context.get("last_price", stock_row.get("last_price")),
        "daily_change_pct": parsed_market_context.get("daily_change_pct", stock_row.get("daily_change_pct")),
        "pe": parsed_market_context.get("pe", parsed_market_context.get("pe_ratio", stock_row.get("pe_ratio"))),
        "market_cap": parsed_market_context.get("market_cap", stock_row.get("market_cap")),
        "dominant_event_type": parsed_market_context.get(
            "dominant_event_type",
            stock_row.get("dominant_event_type") or "other",
        ),
    }

    # Fill missing market context from yfinance fundamentals/quote.
    if market_context.get("pe") is None or market_context.get("market_cap") is None:
        fundamentals = get_fundamentals(symbol)
        if market_context.get("pe") is None:
            market_context["pe"] = fundamentals.get("trailingPE") or fundamentals.get("forwardPE")
        if market_context.get("market_cap") is None:
            market_context["market_cap"] = fundamentals.get("marketCap")

    if market_context.get("last_price") is None or market_context.get("daily_change_pct") is None:
        quote = get_fast_quote(symbol)
        last_price = _to_float(quote.get("last_price"))
        prev_close = _to_float(quote.get("previous_close"))
        if market_context.get("last_price") is None:
            market_context["last_price"] = last_price
        if market_context.get("daily_change_pct") is None and last_price is not None and prev_close not in (None, 0):
            market_context["daily_change_pct"] = ((last_price - prev_close) / prev_close) * 100.0

    # Databricks gold tables don't currently store 52W low/high.
    # Force this fallback when values are missing, and optionally allow always-on via env.
    enrich_52w = (os.getenv("DBX_MARKET_ENRICH_WITH_YFINANCE") or "0").strip().lower() in {"1", "true", "yes", "on"}
    low_52w = None
    high_52w = None
    needs_52w = market_context.get("low_52w") is None or market_context.get("high_52w") is None
    if enrich_52w or needs_52w:
        range_52w = get_52w_range(symbol)
        low_52w = range_52w.get("low_52w")
        high_52w = range_52w.get("high_52w")
    market_context["low_52w"] = low_52w
    market_context["high_52w"] = high_52w
    range_position_pct = None
    try:
        last_price = market_context.get("last_price")
        if (
            last_price is not None
            and low_52w is not None
            and high_52w is not None
            and float(high_52w) != float(low_52w)
        ):
            range_position_pct = ((float(last_price) - float(low_52w)) / (float(high_52w) - float(low_52w))) * 100.0
    except Exception:
        range_position_pct = None
    market_context["range_position_pct"] = range_position_pct

    verdict_label = report_row.get("verdict") or signal
    verdict_reason = report_row.get("risk_assessment") or report_row.get("short_term_outlook") or "Verdict is based on current Gold sentiment aggregates."

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "stock": {
            "symbol": stock_row.get("ticker"),
            "name": stock_row.get("ticker"),
            "sector": stock_row.get("sector"),
            "exchange": None,
            "quantity": str(stock_row.get("quantity")),
            "avg_buy_price": str(stock_row.get("avg_buy_price")),
        },
        "overall_signal": {
            "label": signal,
            "sentiment_score": stock_row.get("sentiment_score_7d") or 0.0,
            "confidence": 0.75,
            "window": "7d",
            "based_on": f"{stock_row.get('news_count') or 0} relevant articles",
        },
        "score_breakdown": {
            "score_24h": stock_row.get("sentiment_score_24h") or 0.0,
            "score_7d": stock_row.get("sentiment_score_7d") or 0.0,
            "trend_direction": stock_row.get("trend_direction") or "steady",
            "news_count": stock_row.get("news_count") or 0,
            "positive_count": stock_row.get("positive_count") or 0,
            "negative_count": stock_row.get("negative_count") or 0,
            "neutral_count": stock_row.get("neutral_count") or 0,
            "high_impact_news_count": stock_row.get("high_impact_news_count") or 0,
            "dominant_event_type": stock_row.get("dominant_event_type") or "other",
        },
        "why_it_changed": [
            report_row.get("sentiment_explanation") or "Sentiment explanation is available from Gold outputs.",
            report_row.get("short_term_outlook") or "Short-term outlook is available from Gold outputs.",
        ],
        "top_news": [
            {
                "ticker": row.get("ticker"),
                "headline": _clean_headline(row.get("cleaned_headline")),
                "source": row.get("source"),
                "url": row.get("url"),
                "published_at": row.get("published_at"),
                "sentiment_label": row.get("sentiment_label"),
                "impact_level": row.get("impact_level"),
                "event_type": stock_row.get("dominant_event_type") or "other",
                "short_explanation_tag": row.get("short_explanation_tag"),
                "confidence_score": 0.75,
                "weighted_score": stock_row.get("sentiment_score_7d") or 0.0,
            }
            for row in news_rows
        ],
        "risk_flags": parse_json_field(report_row.get("risk_flags_json")) or [],
        "analyst_summary": report_row.get("executive_summary") or "Databricks Gold summary is available.",
        "verdict": {"label": verdict_label, "reason": verdict_reason},
        "market_context": market_context,
        "meta": {
            "source": "databricks_gold",
            "provider": "databricks",
            "gold_table": "gold_stock_insight_current",
            "as_of_ts": report_row.get("as_of_ts") or stock_row.get("as_of_ts"),
            "news_window": "24h_preferred",
        },
    }
