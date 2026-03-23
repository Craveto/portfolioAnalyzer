# Portfolio Analyzer 
Now you can play with this webapp on 
https://thankful-forest-0dddffc00.2.azurestaticapps.net/

<img width="1510" height="727" alt="image" src="https://github.com/user-attachments/assets/2aabbf4d-bcc5-432f-807f-5332452406f7" />



Portfolio Analyzer is a full-stack stock portfolio analysis platform built with Django REST Framework, React, and a Databricks-ready analytics layer. It helps a user create portfolios, record buy/sell trades, monitor holdings, explore valuation metrics, review watchlists and price alerts, and analyze portfolio sentiment with report exports.

The project is designed in two layers:

1. A working end-user application for portfolio management and exploratory analysis.
2. A data-platform path that can move the sentiment engine from demo logic to Databricks Bronze, Silver, and Gold tables without changing the frontend contract.

## Live app

The repository currently references this deployed frontend:

`https://portfolio-analyzer-wine.vercel.app/`

## What This Project Demonstrates

- User authentication with Django token auth
- Portfolio creation and portfolio-level organization
- Trade-based holding management using BUY and SELL transactions
- Realized and unrealized P&L tracking
- Market summary for Nifty and Sensex
- Indian stock lookup with live-ish quote enrichment
- Portfolio valuation analysis using P/E, 52-week range, and discount-from-high metrics
- Educational 90-day portfolio forecast
- Holding clustering using explainable features
- Watchlist and price-alert workflows
- Metals and BTC market panels on the landing page
- Stock sentiment and report generation in a Databricks-ready response format
- Report export in Markdown, CSV, and PDF-friendly print flow

## Problem Statement

Retail investors often track portfolios manually in spreadsheets, which makes it difficult to:

- maintain organized holdings across multiple strategies
- understand valuation context quickly
- compare stocks inside a portfolio
- generate explainable analysis for presentations or demos
- extend portfolio data into a proper analytics pipeline

This project solves that by combining a user-facing portfolio app with an analytics workflow that can grow into a medallion-style data platform.

## Product Flow

1. A user lands on the home page and sees market pulse data.
2. The user logs in or signs up.
3. The user creates one or more portfolios.
4. The user records BUY and SELL trades.
5. The backend updates holdings automatically from transactions.
6. The portfolio page shows live-ish prices, P/E, 52-week context, and P&L.
7. The analysis page shows valuation charts, forecast output, sentiment summaries, and stock-level reports.
8. The account area manages profile settings, watchlist items, and alerts.

## Tech Stack

### Frontend

- React 18
- Vite
- React Router
- Plain CSS
- Vercel-friendly SPA configuration

### Backend

- Django 5
- Django REST Framework
- Token Authentication
- WhiteNoise for static files in production
- `yfinance` for market and fundamentals data

### Data and Infrastructure

- SQLite for fast local demo setup
- SQL Server support for local/target database setup
- `DATABASE_URL` support for hosted Postgres-like deployment
- Databricks SQL connector for future Gold-table integration
- Docker Compose file for SQL Server container startup

## Architecture

```text
React Frontend
    |
    v
Django REST API
    |
    +--> Local DB / Hosted DB
    |
    +--> yfinance market data
    |
    +--> Databricks-ready provider layer
            |
            v
      Bronze -> Silver -> Gold analytics pipeline
```

## Main Modules

### 1. Authentication and account

- User registration
- User login
- Token-based authentication
- Account/profile update
- Password change
- Default redirect and default portfolio preferences

### 2. Portfolio management

- Create portfolio
- List portfolios
- Delete portfolio
- View portfolio snapshot
- Holdings derived from transaction activity

### 3. Transaction engine

- BUY updates quantity and weighted average price
- SELL validates available quantity
- SELL calculates realized P&L
- Holdings are automatically created, updated, or removed

### 4. Market and stock data

- Landing market summary for Nifty and Sensex
- Demo top movers
- Symbol search
- Live stock preview
- Quote endpoint
- Stock detail endpoint with fundamentals and 52-week range

### 5. Analysis

- Weighted portfolio P/E
- Per-holding P/E
- 52-week low and high
- Discount from 52-week high
- 52-week range position
- Educational forecast for portfolio value
- Clustering across selected portfolios

### 6. Sentiment insight module

- Portfolio sentiment snapshot
- Stock-level sentiment insight
- Risk flags
- News-based explanation blocks
- Analyst summary output
- Markdown and CSV report generation
- Print-to-PDF flow

### 7. Watchlist and alerts

- Add watchlist items
- Remove watchlist items
- Create ABOVE/BELOW price alerts
- Auto-trigger alerts when conditions are met

## Folder Structure

```text
PortfolioAnalyzer/
|-- backend/                # Django backend
|-- frontend/               # React frontend
|-- databricks/             # Databricks scaffolding, SQL, docs, notebooks, jobs
|-- docs/                   # GitHub-friendly detailed project documentation
|-- docker-compose.yml      # Optional SQL Server container
|-- DEPLOYMENT_RUNBOOK.md   # End-to-end deployment guide
|-- IMPLEMENTATION_BLUEPRINT.md
`-- WORKFLOW_TRACKER.md
```

## Backend Apps

- `api`: authentication, market, stock, portfolio, watchlist, and alert APIs
- `portfolio`: core data models for sectors, stocks, portfolios, holdings, transactions
- `analysis`: valuation, forecast, clustering, sentiment, and Databricks provider layer
- `accounts`: profile settings
- `watchlist`: watchlist items and price alerts

## Data Model

The main entity flow is:

`User -> Portfolio -> Transaction -> Holding -> Stock -> Sector`

Supporting entities:

- `UserProfile`
- `WatchlistItem`
- `PriceAlert`
- `CachedPayload`

## Local Setup

### 1. Clone the repository

```powershell
git clone <your-repo-url>
cd PortFolioAnalyzer
```

### 2. Start the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_stocks
python manage.py runserver 8000
```

Backend default URL:

`http://localhost:8000`

### 3. Start the frontend

Open a new terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Frontend default URL:

`http://localhost:5174`

## Environment Variables

### Backend

Important variables from [backend/.env.example](/e:/Bizmetric/Trae/PortFolioAnalyzer/backend/.env.example):

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DB_ENGINE`
- `DATABASE_URL`
- `DB_CONN_MAX_AGE`
- `CORS_ALLOWED_ORIGINS`
- `FUNDAMENTALS_PROVIDER`
- `RAPIDAPI_KEY`
- `STOCK_INSIGHT_PROVIDER`
- `DBX_HOST`
- `DBX_HTTP_PATH`
- `DBX_TOKEN`
- `ANALYSIS_BACKGROUND_REFRESH`
- `MARKET_WARMUP_TOKEN`

### Frontend

Important variable from [frontend/.env.example](/e:/Bizmetric/Trae/PortFolioAnalyzer/frontend/.env.example):

- `VITE_API_BASE_URL`

## API Overview

### Auth and account

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `GET /api/auth/me/`
- `GET /api/auth/account/`
- `PATCH /api/auth/account/`
- `POST /api/auth/password/change/`

### Dashboard and market

- `GET /api/dashboard/summary/`
- `GET /api/market/summary/`
- `POST /api/market/warm/`
- `GET /api/market/quote/`
- `GET /api/market/metals/summary/`
- `GET /api/market/metals/news/`
- `GET /api/market/metals/quote/`
- `GET /api/market/metals/forecast/`
- `GET /api/market/btc/summary/`
- `GET /api/market/btc/news/`
- `GET /api/market/btc/quote/`
- `GET /api/market/btc/predictions/`

### Stocks and portfolios

- `GET /api/stocks/`
- `GET /api/stocks/live/`
- `GET /api/stocks/detail/`
- `GET /api/stocks/preview/`
- `GET /api/portfolios/`
- `POST /api/portfolios/`
- `GET /api/portfolios/{id}/`
- `DELETE /api/portfolios/{id}/`
- `GET /api/portfolios/{id}/transactions/`
- `POST /api/portfolios/{id}/transactions/`

### Analysis

- `GET /api/analysis/portfolio/{id}/pe/`
- `GET /api/analysis/portfolio/{id}/forecast/`
- `GET /api/analysis/portfolio/{id}/sentiment/`
- `GET /api/analysis/portfolio/{id}/stocks/{symbol}/insight/`
- `GET /api/analysis/portfolio/{id}/stocks/{symbol}/report/?format=md`
- `GET /api/analysis/portfolio/{id}/stocks/{symbol}/report/?format=csv`
- `GET /api/analysis/cluster/`
- `GET /api/analysis/cluster/csv/`

### Databricks sentiment check (backend + cache)

Use this command to verify three things in one run:

- Databricks SQL connectivity
- Gold-table-backed sentiment fetch through backend provider
- cache persistence in `CachedPayload` (stored in your configured Django DB, including Supabase Postgres when `DATABASE_URL` points there)

```powershell
cd backend
python manage.py check_databricks_sentiment --portfolio-id 1 --force
```

For continuous background freshness in hosting, schedule this command (cron/job worker):

```powershell
cd backend
python manage.py warm_sentiment_cache --max-stocks-per-portfolio 3
```

### Watchlist and alerts

- `GET /api/watchlist/`
- `POST /api/watchlist/`
- `DELETE /api/watchlist/{item_id}/`
- `GET /api/alerts/`
- `POST /api/alerts/`
- `DELETE /api/alerts/{alert_id}/`

## Databricks Integration Story

The current repository already contains the transition path from app-first analytics to platform-backed analytics:

- Bronze ingestion definitions
- Silver cleaning and scoring notebook templates
- Gold aggregation templates
- backend provider switch between `demo` and `databricks`
- stable API contracts so the React UI does not need a rewrite later

Use these files for that part of the project:

- [IMPLEMENTATION_BLUEPRINT.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/IMPLEMENTATION_BLUEPRINT.md)
- [WORKFLOW_TRACKER.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/WORKFLOW_TRACKER.md)
- [databricks/README.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/README.md)

## Deployment

The full deployment process is documented in:

- [DEPLOYMENT_RUNBOOK.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/DEPLOYMENT_RUNBOOK.md)

Recommended deployment split:

1. Frontend on Vercel
2. Backend on Render or another Django-friendly host
3. Database on hosted Postgres or SQL Server depending on environment
4. Databricks for the sentiment pipeline when Gold tables are ready

## Documentation Map

- [Full Project Documentation](/e:/Bizmetric/Trae/PortFolioAnalyzer/docs/PROJECT_DOCUMENTATION.md)
- [Deployment Runbook](/e:/Bizmetric/Trae/PortFolioAnalyzer/DEPLOYMENT_RUNBOOK.md)
- [Implementation Blueprint](/e:/Bizmetric/Trae/PortFolioAnalyzer/IMPLEMENTATION_BLUEPRINT.md)
- [Workflow Tracker](/e:/Bizmetric/Trae/PortFolioAnalyzer/WORKFLOW_TRACKER.md)

## Future Improvements

- Full Databricks execution with live Bronze, Silver, and Gold outputs
- Better forecasting models beyond explainable baseline math
- Persistent report history
- More complete live market coverage
- Polling or streaming market refresh
- More advanced alert notifications

## Submission Note

If you are using this repository for academic or portfolio submission, the strongest story is:

1. You built a working full-stack portfolio analysis app.
2. You implemented core investor workflows end to end.
3. You added explainable EDA features and report generation.
4. You prepared the system for a scalable Databricks analytics pipeline.
