# Deployment Runbook

This runbook explains how to deploy Portfolio Analyzer cleanly and present it professionally. It covers local validation, environment preparation, backend deployment, frontend deployment, optional SQL Server setup, and the staged switch to Databricks-backed analytics.

## 1. Deployment Goal

The safest deployment strategy for this project is:

1. deploy a stable frontend
2. deploy a stable backend
3. connect a working database
4. verify the app in `demo` insight mode
5. switch to Databricks only after Gold tables are ready

This prevents the sentiment pipeline from breaking the main portfolio application.

## 2. Recommended Hosting Topology

### Frontend

- Host: Vercel
- Folder: `frontend/`
- Build command: `npm run build`
- Output directory: `dist`

### Backend

- Host: Render or any Django-friendly host
- Folder: `backend/`
- Runtime: Python 3.12
- Start command: `gunicorn edaapp.wsgi`

### Database

Choose one:

- hosted Postgres through `DATABASE_URL`
- SQL Server if your environment requires it
- SQLite only for local/demo use

### Analytics

- Databricks SQL Warehouse
- enabled only after Bronze, Silver, and Gold outputs are available

## 3. Pre-Deployment Checklist

Before deployment, validate these locally:

1. backend installs successfully
2. migrations run successfully
3. `seed_stocks` runs successfully
4. frontend builds successfully
5. login works
6. portfolio creation works
7. trade creation works
8. analysis page loads
9. watchlist and alerts work
10. report download works

Suggested local checks:

```powershell
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_stocks
python manage.py runserver 8000
```

```powershell
cd frontend
npm install
npm run build
npm run dev
```

## 4. Backend Environment Variables

Set these for deployment.

### Core Django

```env
DJANGO_SECRET_KEY=replace-with-strong-secret
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=your-backend-domain.onrender.com
```

### Database

Use either `DATABASE_URL` or MSSQL settings.

#### Option A. Hosted database via URL

```env
DATABASE_URL=your_database_connection_string
```

#### Option B. SQL Server

```env
DB_ENGINE=mssql
MSSQL_NAME=EDAAPP
MSSQL_USER=sa
MSSQL_PASSWORD=YourStrong!Passw0rd
MSSQL_HOST=your-sql-host
MSSQL_PORT=1433
MSSQL_OPTIONS_DRIVER=ODBC Driver 18 for SQL Server
```

### CORS and CSRF

```env
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.vercel.app
CSRF_TRUSTED_ORIGINS=https://your-frontend-domain.vercel.app
```

### Market warmup

```env
MARKET_WARMUP_TOKEN=choose-a-secret-token
```

### Fundamentals provider

```env
FUNDAMENTALS_PROVIDER=auto
RAPIDAPI_KEY=optional_if_used
RAPIDAPI_HOST=apidojo-yahoo-finance-v1.p.rapidapi.com
RAPIDAPI_REGION=IN
RAPIDAPI_LANG=en-US
```

### Insight provider

Keep this in demo mode first:

```env
STOCK_INSIGHT_PROVIDER=demo
```

Switch later only after Databricks Gold is ready:

```env
STOCK_INSIGHT_PROVIDER=databricks
DBX_HOST=your-workspace.cloud.databricks.com
DBX_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DBX_TOKEN=your-databricks-token
```

## 5. Frontend Environment Variables

Set this on Vercel:

```env
VITE_API_BASE_URL=https://your-backend-domain.onrender.com
```

If frontend and backend are eventually served behind the same origin, same-origin `/api` usage can also work, but explicit API base configuration is safer.

## 6. Backend Deployment Steps

### Step 1. Prepare backend service

Use the `backend/` directory as the service root.

### Step 2. Install dependencies

The backend depends on:

- Django
- DRF
- WhiteNoise
- database connectors
- `yfinance`
- `pandas`
- `numpy`
- Databricks SQL connector

They are already listed in [backend/requirements.txt](/e:/Bizmetric/Trae/PortFolioAnalyzer/backend/requirements.txt).

### Step 3. Configure build and start commands

Typical commands:

Build command:

```powershell
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_stocks
```

Start command:

```powershell
gunicorn edaapp.wsgi
```

### Step 4. Set env variables

Set the backend variables listed above.

### Step 5. Deploy

Once deployed, verify:

1. `/`
2. `/api/market/summary/`
3. `/api/auth/register/`
4. a token-protected portfolio route after login

## 7. Frontend Deployment Steps

### Step 1. Import the `frontend/` folder into Vercel

### Step 2. Configure build settings

- Framework preset: Vite
- Build command: `npm run build`
- Output directory: `dist`

### Step 3. Set env variable

```env
VITE_API_BASE_URL=https://your-backend-domain.onrender.com
```

### Step 4. Keep SPA routing enabled

[frontend/vercel.json](/e:/Bizmetric/Trae/PortFolioAnalyzer/frontend/vercel.json) already rewrites all routes to `index.html`, which is required for React Router routes like:

- `/dashboard`
- `/portfolio/:id`
- `/analysis/:id`
- `/chart/:id`
- `/account`

### Step 5. Verify the deployed frontend

Check:

1. landing page loads
2. login modal works
3. dashboard loads after auth
4. portfolio route opens directly in browser refresh
5. analysis route opens directly in browser refresh

## 8. Optional SQL Server Local Deployment

If you want to demonstrate SQL Server locally:

### Step 1. Start container

```powershell
docker compose up -d
```

### Step 2. Set backend `.env`

```env
DB_ENGINE=mssql
MSSQL_NAME=EDAAPP
MSSQL_USER=sa
MSSQL_PASSWORD=YourStrong!Passw0rd
MSSQL_HOST=localhost
MSSQL_PORT=1433
MSSQL_OPTIONS_DRIVER=ODBC Driver 18 for SQL Server
```

### Step 3. Run migrations and seed

```powershell
cd backend
python manage.py migrate
python manage.py seed_stocks
python manage.py runserver 8000
```

## 9. Warm Cache and Free-Tier Stability

Because market data can be slow or variable on low-cost/free infrastructure, this project supports pre-warming the market cache.

Endpoint:

`POST /api/market/warm/`

Use:

- `X-Warmup-Token` header
- or `?token=...`

Recommended process:

1. set `MARKET_WARMUP_TOKEN`
2. call `/api/market/warm/` from an external scheduler
3. keep refresh interval around 1 to 5 minutes

This improves landing-page responsiveness.

## 10. Databricks Rollout Process

Do not switch to Databricks in one step. Use a staged rollout.

### Stage 1. Keep application working in demo mode

```env
STOCK_INSIGHT_PROVIDER=demo
```

Verify:

- portfolio sentiment endpoint responds
- stock insight endpoint responds
- report downloads work

### Stage 2. Prepare Databricks foundation

Run these in order:

1. [01_medallion_schema.sql](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/sql/01_medallion_schema.sql)
2. [01_ingest_supabase_portfolio.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/01_ingest_supabase_portfolio.py)
3. [02_validate_bronze_portfolio_snapshot.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/02_validate_bronze_portfolio_snapshot.py)
4. [03_build_active_ticker_list.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/03_build_active_ticker_list.py)
5. [04_fetch_news_for_tickers.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/04_fetch_news_for_tickers.py)
6. [05_fetch_market_context.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/05_fetch_market_context.py)
7. [06_clean_portfolio_data.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/06_clean_portfolio_data.py)
8. [07_clean_news_data.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/07_clean_news_data.py)
9. [08_score_news_with_finbert.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/08_score_news_with_finbert.py)
10. [09_aggregate_stock_gold_tables.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/09_aggregate_stock_gold_tables.py)
11. [10_aggregate_portfolio_gold_tables.py](/e:/Bizmetric/Trae/PortFolioAnalyzer/databricks/notebooks/10_aggregate_portfolio_gold_tables.py)

### Stage 3. Validate Gold tables

Check that Gold outputs have real rows and expected fields before touching production settings.

### Stage 4. Add Databricks env variables

```env
DBX_HOST=your-workspace.cloud.databricks.com
DBX_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
DBX_TOKEN=your-token
```

### Stage 5. Switch provider

```env
STOCK_INSIGHT_PROVIDER=databricks
```

### Stage 6. Regression test

Retest:

1. `GET /api/analysis/portfolio/{id}/sentiment/`
2. `GET /api/analysis/portfolio/{id}/stocks/{symbol}/insight/`
3. `GET /api/analysis/portfolio/{id}/stocks/{symbol}/report/?format=md`
4. `GET /api/analysis/portfolio/{id}/stocks/{symbol}/report/?format=csv`

## 11. Verification Checklist After Deployment

### User flow

1. register user
2. log in
3. create portfolio
4. add BUY transaction
5. add SELL transaction
6. open dashboard
7. open portfolio page
8. open analysis page
9. add watchlist item
10. create alert

### Technical flow

1. backend serves API without 500 errors
2. frontend points to correct backend URL
3. CORS is configured correctly
4. token auth works
5. market summary returns data
6. portfolio endpoints save data
7. analysis endpoints return payloads
8. report download endpoints work

## 12. Rollback Strategy

If a deployment issue appears:

1. revert frontend env or deployment to previous build
2. keep backend alive in `STOCK_INSIGHT_PROVIDER=demo`
3. remove Databricks env values temporarily if they are causing failures
4. restore previous backend release

Most importantly:

- do not block the whole app because of sentiment integration
- the portfolio product should remain usable even if Databricks is not ready

## 13. Common Deployment Problems

### CORS errors

Cause:

- frontend URL missing from backend allowed origins

Fix:

- update `CORS_ALLOWED_ORIGINS`
- update `CSRF_TRUSTED_ORIGINS`

### Blank React page on refresh

Cause:

- SPA routing not configured

Fix:

- keep [frontend/vercel.json](/e:/Bizmetric/Trae/PortFolioAnalyzer/frontend/vercel.json) in deployment

### Slow market pages

Cause:

- cold start or upstream quote delay

Fix:

- use cache warm endpoint
- keep snapshots enabled

### Fundamentals missing

Cause:

- some upstream finance endpoints are inconsistent

Fix:

- keep `FUNDAMENTALS_PROVIDER=auto`
- optionally configure RapidAPI

### Databricks insight failure

Cause:

- invalid host, token, HTTP path, or empty Gold tables

Fix:

- switch back to `STOCK_INSIGHT_PROVIDER=demo`
- validate Databricks query path first

## 14. Best Presentation Path for GitHub or Viva

For a safe and professional demo:

1. deploy frontend and backend first
2. demonstrate login, portfolio creation, trades, and analysis
3. show watchlist and alerts
4. download one report
5. then explain the Databricks pipeline as the scaling layer

This presents the project honestly:

- the app is already functional
- the analytics pipeline is architected and scaffolded
- the production-scale sentiment layer is the next rollout step
