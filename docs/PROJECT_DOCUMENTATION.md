# Portfolio Analyzer Project Documentation

## 1. Introduction

Portfolio Analyzer is a full-stack web application created to help users manage investment portfolios and understand them using exploratory analysis, valuation indicators, and sentiment-style insights. The project combines application engineering with analytics engineering, which makes it suitable both as a software project and as a data-platform project.

This document explains the project from beginning to end in a topic-wise format so it can be submitted on GitHub as complete documentation.

## 2. Project Objective

The main objective of the project is to build an application where a user can:

- register and log in securely
- create one or more portfolios
- add stock transactions
- automatically maintain holdings
- see live-ish market context
- study valuation metrics such as P/E and 52-week discount
- review portfolio forecasts
- track stocks with watchlists and alerts
- generate sentiment-style reports
- prepare the system for a Databricks analytics pipeline

## 3. Problem the Project Solves

Most beginner and intermediate investors track portfolios in spreadsheets. That causes several issues:

- holdings are not updated automatically from trades
- valuation comparison is slow and manual
- portfolio-wise analysis is difficult
- reports are not easy to generate
- scaling toward proper analytics architecture is hard

This project solves that by putting portfolio management, market data, analysis, and reporting inside one integrated platform.

## 4. Project Scope

### Current implemented scope

- authentication
- portfolio CRUD
- transaction engine
- holdings and P&L
- market summary
- stock search and quote preview
- valuation analysis
- educational forecast
- watchlist and price alerts
- stock clustering
- sentiment-style stock insight module
- report downloads
- Databricks-ready backend/provider layer

### Planned scope

- live Databricks Bronze ingestion
- Silver cleaning and scoring execution
- Gold-table-backed sentiment APIs
- report persistence
- stronger production analytics

## 5. Users and Use Cases

### Target users

- students building a finance/data project
- retail investors wanting organized portfolio analysis
- evaluators or teachers reviewing project architecture
- recruiters reviewing full-stack and analytics capability

### Main use cases

1. User creates an account and logs in.
2. User creates portfolios for different investment themes.
3. User records BUY and SELL transactions.
4. User opens a portfolio and inspects holdings.
5. User checks P/E, last price, discount, and unrealized P&L.
6. User opens Analysis to view charts, forecast, and sentiment.
7. User downloads Markdown or CSV reports.
8. User maintains watchlist items and price alerts.

## 6. Technology Stack

### Frontend technologies

- React
- Vite
- React Router
- CSS

### Backend technologies

- Django
- Django REST Framework
- Django Token Authentication
- WhiteNoise
- `yfinance`
- `pandas`
- `numpy`

### Data and deployment technologies

- SQLite
- SQL Server
- Docker Compose
- Databricks SQL Connector
- Vercel-compatible frontend config
- Render-style Django deployment setup

## 7. High-Level Architecture

```text
User
  |
  v
React Frontend
  |
  v
Django REST Backend
  |
  +--> Database (SQLite / SQL Server / hosted DB)
  +--> yfinance APIs
  +--> Databricks Provider Layer
           |
           v
     Bronze -> Silver -> Gold
```

## 8. Project Structure

### Root

- `README.md`: GitHub overview
- `DEPLOYMENT_RUNBOOK.md`: deployment instructions
- `IMPLEMENTATION_BLUEPRINT.md`: Databricks integration strategy
- `WORKFLOW_TRACKER.md`: status tracker

### Backend

- `backend/api/`: auth, portfolio, watchlist, alerts, market APIs
- `backend/portfolio/`: domain models
- `backend/analysis/`: analysis, clustering, forecast, sentiment, provider abstraction
- `backend/accounts/`: user profile
- `backend/watchlist/`: watchlist and price alerts

### Frontend

- `frontend/src/pages/`: page-level UI
- `frontend/src/components/`: reusable UI components
- `frontend/src/api.js`: API client layer

### Databricks

- `databricks/sql/`: medallion schema and gold views
- `databricks/notebooks/`: notebook templates for ingestion and transformations
- `databricks/jobs/`: job workflow definition
- `databricks/docs/`: notebook/process documentation

## 9. Development Journey From Beginning to End

### Phase 1. Base full-stack setup

The project started as a Django + React application. The first goal was to create a working end-to-end product where:

- frontend handles the UI
- backend handles API and business logic
- database stores users, portfolios, stocks, holdings, and transactions

### Phase 2. Authentication

User authentication was added using Django and DRF token auth. This made it possible to protect portfolio routes and maintain user-specific data.

Implemented flow:

1. register user
2. log in user
3. issue auth token
4. call protected APIs using token header

### Phase 3. Portfolio and transaction engine

Instead of manually editing holdings, the project was designed to use transactions as the source of truth.

Why this matters:

- more realistic portfolio workflow
- easier audit trail
- accurate realized P&L for SELL trades
- holdings remain derived, not manually inconsistent

Implemented logic:

1. BUY creates or updates holding
2. weighted average price is recalculated
3. SELL validates available quantity
4. realized P&L is computed on SELL
5. holding is removed when quantity becomes zero

### Phase 4. Market integration

The application then integrated `yfinance` to fetch:

- index data
- stock quotes
- stock fundamentals
- 52-week range
- historical prices

This allowed the app to move from basic CRUD to analysis-driven functionality.

### Phase 5. Portfolio analytics

Once market context was available, the next step was to create EDA-style analysis features:

- weighted portfolio P/E
- per-stock P/E
- 52-week low and high
- discount from 52-week high
- 52-week range position
- chart views for easier interpretation

### Phase 6. Forecast module

An explainable educational forecast was added for portfolio value. The model uses historical prices to estimate a simple future path.

Reason for this approach:

- easy to explain in a presentation
- lightweight implementation
- useful for EDA and demo purposes

### Phase 7. Watchlist and alerts

To make the application more complete as a user product, watchlist and price-alert features were added.

Implemented behavior:

- save stocks in watchlist
- create ABOVE or BELOW price alerts
- auto-check and trigger conditions when data is fetched

### Phase 8. Clustering

To increase the analytics value of the project, clustering was added. The application groups holdings using explainable metrics:

- P/E
- discount from 52-week high
- 52-week position
- log-transformed price

This helps compare holdings beyond raw table data.

### Phase 9. Sentiment and insight module

The next stage was to create a stock insight layer for teacher-demo and reporting use cases. This includes:

- portfolio sentiment summary
- stock-level signal
- top news blocks
- risk flags
- analyst summary
- report download options

Important design decision:

The response contract was intentionally made compatible with a future Databricks Gold output so the frontend does not need to be rewritten later.

### Phase 10. Databricks-ready architecture

The final major design step was to scaffold a medallion architecture for real analytics scaling:

1. Bronze for raw ingested data
2. Silver for cleaned and scored data
3. Gold for UI-ready insight outputs

This is documented in the repo and partially scaffolded in code and notebook templates.

## 10. Frontend Module Explanation

### Landing page

Purpose:

- introduce the product
- show market pulse
- present metals and BTC modules
- guide user toward login and portfolio creation

### Dashboard page

Purpose:

- show KPIs
- show portfolio list
- show recent activity
- preview watchlist
- provide quick actions

### Portfolio page

Purpose:

- display holdings
- record trades
- show stock-level metrics
- access clustering and quick charts

### Analysis page

Purpose:

- show valuation overview
- show forecast chart
- show portfolio sentiment snapshot
- show stock insight details
- allow report downloads

### Account page

Purpose:

- manage user profile
- manage default portfolio
- manage watchlist
- manage alerts

## 11. Backend Module Explanation

### `api` app

Responsible for:

- auth
- account APIs
- market APIs
- stock lookup
- portfolio APIs
- transaction endpoints
- watchlist and alert endpoints
- dashboard summary

### `portfolio` app

Responsible for domain models:

- `Sector`
- `Stock`
- `Portfolio`
- `Holding`
- `Transaction`

### `analysis` app

Responsible for:

- portfolio P/E analysis
- portfolio forecast
- clustering
- sentiment provider abstraction
- Databricks connector scaffolding
- report generation

### `accounts` app

Responsible for:

- `UserProfile`
- redirect preferences
- default portfolio preferences

### `watchlist` app

Responsible for:

- `WatchlistItem`
- `PriceAlert`

## 12. Database Design

### Core entities

#### User

Stores registered users and authentication identity.

#### Portfolio

Represents one basket of investments owned by a user.

#### Stock

Represents a market instrument such as an NSE or BSE stock.

#### Holding

Represents the current quantity and average buy price for a stock inside a portfolio.

#### Transaction

Represents BUY or SELL activity and serves as the operational history.

### Supporting entities

#### Sector

Used to categorize stocks.

#### UserProfile

Stores profile metadata and user preferences.

#### WatchlistItem

Stores a user-saved stock outside a portfolio.

#### PriceAlert

Stores threshold-based alerts for watchlist-like monitoring.

#### CachedPayload

Stores API snapshots for faster repeat loads and reduced external calls.

## 13. Important Business Logic

### Transaction processing

BUY flow:

1. validate stock and inputs
2. create holding if missing
3. else update quantity and weighted average buy price
4. save BUY transaction

SELL flow:

1. validate stock and existing holding
2. ensure sell quantity is available
3. calculate realized P&L
4. reduce or remove holding
5. save SELL transaction

### Cache strategy

The project uses cached payloads for:

- landing market summary
- dashboard summary
- portfolio snapshot
- portfolio P/E
- Databricks-style analysis payloads

Why it is useful:

- faster UI loads
- fewer upstream calls
- better behavior on free-tier hosting
- graceful fallback when live data is temporarily unavailable

### Sentiment provider abstraction

The backend supports:

- `STOCK_INSIGHT_PROVIDER=demo`
- `STOCK_INSIGHT_PROVIDER=databricks`

This makes the current app usable today while keeping the architecture ready for future platform-backed analytics.

## 14. Key Features Implemented

### Functional features

- registration and login
- account settings
- dashboard KPIs
- portfolio creation
- transaction-based holdings
- stock search and preview
- quote and fundamentals fetch
- watchlist
- price alerts
- portfolio analysis
- clustering
- forecast
- sentiment insight
- Markdown/CSV reports
- PDF-friendly print flow

### Engineering features

- provider abstraction
- caching for hosted performance
- local storage warm cache in frontend
- deployment-friendly env configuration
- SQL Server option
- Databricks medallion scaffolding

## 15. API Flow Example

### End-to-end user workflow

1. `POST /api/auth/register/`
2. `POST /api/auth/login/`
3. `POST /api/portfolios/`
4. `POST /api/portfolios/{id}/transactions/`
5. `GET /api/portfolios/{id}/`
6. `GET /api/analysis/portfolio/{id}/pe/`
7. `GET /api/analysis/portfolio/{id}/forecast/`
8. `GET /api/analysis/portfolio/{id}/sentiment/`
9. `GET /api/analysis/portfolio/{id}/stocks/{symbol}/report/?format=md`

## 16. Setup Steps

### Backend setup

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

### Frontend setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

### Optional SQL Server setup

```powershell
docker compose up -d
```

Then configure MSSQL variables in the backend `.env`.

## 17. Deployment Strategy

The project is easiest to deploy using a split architecture:

1. frontend on Vercel
2. backend on Render or equivalent
3. database on hosted DB
4. Databricks connected later for analytics scaling

Full deployment steps are available in [DEPLOYMENT_RUNBOOK.md](/e:/Bizmetric/Trae/PortFolioAnalyzer/DEPLOYMENT_RUNBOOK.md).

## 18. Databricks Workflow

The repo includes a clear medallion path:

### Bronze

- portfolio snapshot ingestion
- raw news ingestion
- raw market context ingestion

### Silver

- portfolio cleaning
- news cleaning
- sentiment scoring

### Gold

- stock insight current view
- stock news view
- portfolio summary
- report dataset

Suggested execution order:

1. medallion schema SQL
2. Bronze ingestion notebook
3. Bronze validation notebook
4. active ticker build
5. news ingestion
6. market context ingestion
7. portfolio cleaning
8. news cleaning
9. FinBERT scoring
10. stock gold aggregation
11. portfolio gold aggregation

## 19. Strengths of the Project

- full-stack implementation, not just a UI mockup
- realistic transaction-based portfolio flow
- explainable analytics
- report generation
- scalable architecture direction
- clean separation between app layer and data-platform layer
- strong demo story for both software and analytics reviewers

## 20. Current Limitations

- some fundamentals depend on upstream data availability
- forecast is educational, not production-grade prediction
- alert checking is request-time based, not a dedicated scheduler
- Databricks notebooks are scaffolded but not fully executed live from this repo
- market data coverage is focused on current project use cases

## 21. Future Enhancements

- live Databricks job execution
- persisted report history
- notification channels for alerts
- richer forecasting models
- broader market coverage
- more advanced portfolio comparisons
- performance dashboards for teachers or recruiters

## 22. Conclusion

Portfolio Analyzer is a complete project that shows both product thinking and engineering depth. It is not only a CRUD application; it demonstrates:

- user management
- financial workflow logic
- analytics visualization
- report generation
- deployment awareness
- future-ready data-platform design

For GitHub submission, this project can be presented as a full-stack portfolio analysis system with a Databricks-ready analytics backbone.
