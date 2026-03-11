# Azure deployment roadmap

This branch is prepared for:

- `frontend` -> Azure Static Web Apps
- `backend` -> Azure App Service (Linux, Python)
- database -> preferred: Azure Database for PostgreSQL or Supabase Postgres

## Why Postgres is the smooth path

The current backend already supports `DATABASE_URL`, `dj-database-url`, and `psycopg`.
That means Azure App Service can connect to PostgreSQL/Supabase directly with no ODBC driver work.

Use SQL Server only if you explicitly want to keep the SQL Server stack and are ready for more deployment friction.

## Files added for Azure

- `backend/startup.azure.sh`
- `backend/.env.azure.postgres.example`
- `backend/.env.azure.sqlserver.example`
- `frontend/.env.azure.example`
- `frontend/public/staticwebapp.config.json`

## Backend: App Service setup

### 1. Create App Service

- OS: Linux
- Runtime: Python
- Startup command:

```sh
sh startup.azure.sh
```

### 2. Set app settings

For the smooth path, copy values from:

- `backend/.env.azure.postgres.example`

If you insist on SQL Server, use:

- `backend/.env.azure.sqlserver.example`

### 3. Deployment source

- GitHub repo
- Branch: `azureDeploy`
- Workflow: `.github/workflows/azure-backend.yml`

### 4. Working directory

Deploy the `backend` app on App Service.

## Frontend: Static Web Apps setup

### 1. Create Static Web App

- Source: GitHub
- Branch: `azureDeploy`
- App location: `frontend`
- Output location: `dist`

### 2. Frontend environment variable

Use:

- `frontend/.env.azure.example`

## Database choice

### Recommended

- Azure Database for PostgreSQL
- or Supabase Postgres

### Alternative

- Azure SQL Database (project-compatible, but less smooth on App Service Linux)

## No conflict with Render

- Keep `main` for Render/Vercel
- Keep `azureDeploy` for Azure deployment config
- Use separate DBs and separate env vars
- Do not reuse Render backend/frontend URLs in Azure

## Deploy order

1. Create database
2. Create backend App Service
3. Add backend environment variables
4. Set startup command to `sh startup.azure.sh`
5. Create frontend Static Web App
6. Add `VITE_API_BASE_URL`
7. Test login, dashboard, portfolio, P/E

## Important backend fix

If App Service starts with `ModuleNotFoundError: No module named 'django'`, the deployment package was copied but dependencies were not available at runtime.

This branch fixes that by:

- deploying only the `backend/` folder as the web root
- bootstrapping a local `antenv` virtual environment in `startup.azure.sh`
- installing `requirements.txt` before migrations and Gunicorn start

Use this App Service startup command:

```sh
sh startup.azure.sh
```
