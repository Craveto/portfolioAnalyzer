from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


FINANCE_QA: list[dict[str, str]] = [
    {"q": "what is stock market", "a": "The stock market is a marketplace where investors buy and sell ownership shares of companies. Prices move with earnings outlook, liquidity, macro data, and demand-supply."},
    {"q": "what is a stock", "a": "A stock represents partial ownership in a company. If the company grows profits and valuation, shareholders may benefit through price appreciation or dividends."},
    {"q": "what is ipo", "a": "IPO means Initial Public Offering, when a private company first sells shares to public investors on an exchange."},
    {"q": "what is market cap", "a": "Market cap is company value in the market: share price multiplied by total outstanding shares."},
    {"q": "what is large cap mid cap small cap", "a": "Large-cap companies are generally more stable, mid-caps balance growth and risk, and small-caps are usually higher risk with potentially higher growth."},
    {"q": "what is pe ratio", "a": "P/E ratio = Price per Share divided by Earnings per Share. Compare P/E within the same sector for better context."},
    {"q": "what is pb ratio", "a": "P/B ratio = Market Price divided by Book Value per Share. It is often useful for banks and asset-heavy sectors."},
    {"q": "what is ev ebitda", "a": "EV/EBITDA compares enterprise value (equity + debt - cash) with operating earnings before interest, tax, depreciation, and amortization. It helps compare firms with different debt levels."},
    {"q": "difference between pe and ev ebitda", "a": "P/E is equity-only and affected by capital structure and accounting profit, while EV/EBITDA is capital-structure-aware and often better for comparing operating valuation across companies."},
    {"q": "what is eps", "a": "EPS (Earnings Per Share) is net profit available to shareholders divided by number of shares. It is a key profitability metric."},
    {"q": "what is beta", "a": "Beta measures how much a stock tends to move versus the market. Around 1 means market-like volatility, above 1 higher volatility, below 1 lower volatility."},
    {"q": "what is alpha", "a": "Alpha is excess return over a benchmark after adjusting for risk. Positive alpha indicates outperformance versus benchmark expectation."},
    {"q": "what is volatility", "a": "Volatility is how much returns fluctuate over time. Higher volatility means larger price swings and usually higher risk."},
    {"q": "what is drawdown", "a": "Drawdown is the decline from a portfolio’s peak value to a subsequent low. Maximum drawdown measures worst peak-to-trough loss."},
    {"q": "what is diversification", "a": "Diversification means spreading investments across sectors, themes, and assets to reduce concentration risk."},
    {"q": "what is asset allocation", "a": "Asset allocation is dividing money across asset classes (equity, debt, cash, gold, etc.) based on goals, horizon, and risk tolerance."},
    {"q": "what is rebalancing", "a": "Rebalancing is periodically adjusting portfolio weights back to target allocation to control risk drift."},
    {"q": "what is sip", "a": "SIP (Systematic Investment Plan) is investing a fixed amount regularly, helping discipline and reducing market timing risk."},
    {"q": "what is lumpsum investing", "a": "Lumpsum investing means investing a large amount at once. It can outperform in rising markets but has higher timing risk."},
    {"q": "what is rupee cost averaging", "a": "Rupee-cost averaging means buying more units when prices are low and fewer when prices are high via regular investing."},
    {"q": "what is nse and bse", "a": "NSE and BSE are India’s major exchanges. NSE often has higher liquidity in many active counters, while BSE has a broader listed universe."},
    {"q": "difference between nse and bse", "a": "Both are major Indian exchanges. Stocks may be listed on both with slight price differences due to liquidity and order flow."},
    {"q": "what is bid ask spread", "a": "Bid-ask spread is the difference between highest buy bid and lowest sell ask. Smaller spread usually indicates better liquidity."},
    {"q": "what is volume in stock market", "a": "Volume is number of shares traded in a period. Rising volume can validate price moves."},
    {"q": "what is liquidity", "a": "Liquidity is how easily an asset can be bought/sold without moving price too much. High liquidity usually means lower transaction impact."},
    {"q": "what is stop loss", "a": "Stop-loss is a predefined price level to limit downside on a position. It enforces risk discipline."},
    {"q": "what is trailing stop loss", "a": "A trailing stop moves with favorable price movement and helps lock gains while limiting downside."},
    {"q": "what is support and resistance", "a": "Support is a zone where buying interest may emerge; resistance is where selling pressure may appear."},
    {"q": "what is moving average", "a": "A moving average smooths price data over a chosen period to help identify trend direction."},
    {"q": "what is rsi", "a": "RSI is a momentum oscillator (0-100). Very high readings can indicate overbought conditions; very low can indicate oversold, but context matters."},
    {"q": "what is macd", "a": "MACD is a trend/momentum indicator based on moving averages. Signal line crossovers and histogram changes are commonly used cues."},
    {"q": "what is intrinsic value", "a": "Intrinsic value is estimated fair value based on future cash flows, growth, and risk assumptions."},
    {"q": "what is dcf", "a": "DCF (Discounted Cash Flow) values a business by discounting expected future cash flows to present value."},
    {"q": "what is dividend yield", "a": "Dividend yield = annual dividend per share divided by share price. It indicates cash return relative to current price."},
    {"q": "what is dividend payout ratio", "a": "Dividend payout ratio is the share of net earnings paid as dividends. Very high payout may reduce reinvestment capacity."},
    {"q": "what is free cash flow", "a": "Free cash flow is operating cash flow minus capital expenditure. It shows cash left for debt reduction, dividends, or growth."},
    {"q": "what is roe", "a": "ROE (Return on Equity) measures profit generated per unit of shareholder equity."},
    {"q": "what is roce", "a": "ROCE (Return on Capital Employed) measures operating profitability relative to total capital used in business."},
    {"q": "what is debt to equity ratio", "a": "Debt-to-equity compares total debt with shareholder equity. Higher values can mean higher financial risk."},
    {"q": "what is interest coverage ratio", "a": "Interest coverage shows how comfortably a company can service interest payments from operating earnings."},
    {"q": "what is promoter holding", "a": "Promoter holding is percentage owned by promoters/founders. Trend and pledging context matter more than one-time number."},
    {"q": "what is fii and dii", "a": "FII are foreign institutional investors and DII are domestic institutional investors. Their flow trends can affect market sentiment."},
    {"q": "what is circuit limit", "a": "Circuit limits are exchange-defined price movement bands to control extreme volatility in a single session."},
    {"q": "what is t1 settlement", "a": "T+1 settlement means trade obligations settle one business day after trade date."},
    {"q": "what is demat account", "a": "A Demat account holds securities electronically. A trading account is used to place buy/sell orders."},
    {"q": "what is cnc and intraday", "a": "CNC is delivery-based buying for holding positions. Intraday positions are opened and closed within same trading day."},
    {"q": "what is margin trading", "a": "Margin trading lets you trade with borrowed funds, increasing potential returns and risks. Strict risk controls are essential."},
    {"q": "what is futures and options", "a": "Futures and options are derivatives linked to underlying assets. They can be used for hedging or speculation and involve higher risk."},
    {"q": "what is option premium", "a": "Option premium is the price paid to buy an option contract. It reflects intrinsic value, time value, and implied volatility."},
    {"q": "what is implied volatility", "a": "Implied volatility is market-implied expectation of future price movement, derived from option prices."},
    {"q": "what is theta decay", "a": "Theta decay is reduction in option time value as expiry approaches, all else equal."},
    {"q": "what is hedging in stock market", "a": "Hedging means taking offsetting positions to reduce downside risk in a portfolio."},
    {"q": "what is risk reward ratio", "a": "Risk-reward ratio compares potential loss to potential gain for a trade setup. Favorable asymmetry improves decision quality over time."},
    {"q": "what is position sizing", "a": "Position sizing decides how much capital to allocate per trade based on conviction and risk tolerance."},
    {"q": "what is portfolio turnover", "a": "Portfolio turnover measures how frequently holdings are changed. Higher turnover can increase costs and tax impact."},
    {"q": "what is tax loss harvesting", "a": "Tax-loss harvesting means realizing losses to offset gains and potentially reduce tax burden, subject to local rules."},
    {"q": "what is etf", "a": "ETF is an exchange-traded fund tracking an index, sector, commodity, or strategy and is traded like a stock."},
    {"q": "what is index fund", "a": "An index fund passively tracks a benchmark index. It typically offers low-cost diversified exposure."},
    {"q": "what is expense ratio", "a": "Expense ratio is annual fund management cost charged to investors, expressed as a percentage of assets."},
    {"q": "what is sharpe ratio", "a": "Sharpe ratio measures risk-adjusted return: excess return per unit of volatility."},
    {"q": "what is sortino ratio", "a": "Sortino ratio is like Sharpe but penalizes only downside volatility, focusing on harmful risk."},
    {"q": "what is benchmark in investing", "a": "A benchmark is a reference index used to evaluate portfolio performance and risk-adjusted outperformance."},
]


def _normalize(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def lookup_finance_answer(question: str, min_score: float = 0.73) -> dict[str, Any] | None:
    qn = _normalize(question)
    if not qn:
        return None

    best = None
    best_score = 0.0
    qn_tokens = set(qn.split())
    for item in FINANCE_QA:
        k = _normalize(item.get("q") or "")
        if not k:
            continue
        if qn == k:
            return {"answer": item.get("a", ""), "topic": k, "score": 1.0}
        ratio = SequenceMatcher(None, qn, k).ratio()
        overlap = 0.0
        k_tokens = set(k.split())
        if qn_tokens and k_tokens:
            overlap = len(qn_tokens.intersection(k_tokens)) / float(len(qn_tokens.union(k_tokens)))
        score = (ratio * 0.68) + (overlap * 0.32)
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= min_score:
        return {"answer": best.get("a", ""), "topic": _normalize(best.get("q", "")), "score": round(best_score, 4)}
    return None
