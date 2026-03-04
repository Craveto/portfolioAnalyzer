# PortFolioAnalyzer (EDA App)

Day-1 deliverable: a working Django (REST) + React app with login, portfolio CRUD, and live-ish Indian market data via `yfinance`.

## What you can demo (Day 1)

1) Landing page loads Nifty/Sensex + “Top 10 movers” (demo universe)  
2) After ~5 seconds a Login/Signup modal appears  
3) Login → Dashboard → Create portfolio → Add a holding (CRUD) → See it listed

## Tech

- Backend: Django + DRF + Token auth (Day-1)
- Frontend: React (Vite)
- DB target: SQL Server (optional sqlite fallback for quick demo)
- Market data: `yfinance` (Yahoo Finance)

## Run (Local)

### Backend (Django)

From repo root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env

# sqlite quick demo (default):
python manage.py migrate
python manage.py seed_stocks
python manage.py runserver 8000
```

Backend runs at `http://localhost:8000`.

### Frontend (React)

In a new terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

## SQL Server option (target DB)

1) Set `backend/.env`:

```
DB_ENGINE=mssql
MSSQL_NAME=EDAAPP
MSSQL_USER=sa
MSSQL_PASSWORD=YourStrong!Passw0rd
MSSQL_HOST=localhost
MSSQL_PORT=1433
MSSQL_OPTIONS_DRIVER=ODBC Driver 18 for SQL Server
```

2) Ensure **ODBC Driver 18 for SQL Server** is installed (required by `pyodbc`).

3) Run:

```powershell
cd backend
python manage.py migrate
python manage.py seed_stocks
python manage.py runserver 8000
```

### SQL Server via Docker (optional)

If you have Docker Desktop:

```powershell
docker compose up -d
```

Then use the `mssql` env settings above.

## API endpoints (Day 1)

- `POST /api/auth/register/`
- `POST /api/auth/login/` (returns DRF token)
- `GET /api/auth/me/`
- `GET /api/market/summary/` (Nifty/Sensex + top movers)
- `GET /api/market/quote/?symbol=RELIANCE.NS` (single symbol quote)
- `GET /api/stocks/?q=...` (search)
- `GET /api/stocks/live/?q=...` (live search via yfinance; India tickers only)
- `GET/POST /api/portfolios/`
- `GET/DELETE /api/portfolios/{id}/`
- `GET/POST /api/portfolios/{id}/holdings/`
- `PATCH/DELETE /api/portfolios/{id}/holdings/{holding_id}/`
- `GET/POST /api/portfolios/{id}/transactions/`
- `GET /api/analysis/portfolio/{id}/pe/` (P/E analysis for holdings)

## Notes (EDA-friendly storage)

- This Day-1 version fetches market data on-demand (cached ~30 seconds) and **does not** store large time-series in SQL Server.
- Next modules: save only portfolio tickers’ daily snapshots to file storage (CSV/Parquet) for EDA & prediction without bloating SQL.
