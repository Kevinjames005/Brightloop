# Brightloop backend

FastAPI service backed by Supabase (Postgres). See the [root README](../README.md) for full
setup, including the SQL migrations and the `.env` values.

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.\venv\Scripts\uvicorn app.main:app --reload
```

- Interactive API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## Layout

```
app/api/v1/endpoints/   auth, users, products, variants, plans, billing (subscriptions, invoices, payments, reports)
app/services/           business logic and Supabase queries (store.py holds the billing data access)
app/schemas/            Pydantic request and response models
app/core/               config, database client, security, dependencies, money helpers
sql/                    ordered migrations 001 to 005 (run in the Supabase SQL Editor)
scripts/                live_smoke.ps1 (API smoke test) and cleanup_smoke.py
```

## Roles

`admin` manages users, catalog, taxes and discounts. `staff` runs quotes, subscriptions,
billing and payments. `customer` only sees and pays their own subscriptions and invoices.
