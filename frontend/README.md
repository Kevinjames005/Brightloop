# Brightloop frontend

A dependency-free static web app (plain HTML/CSS/JS, no build step) that talks to the
backend REST API. It is fully separate from `backend/`.

## Run

```powershell
# 1. backend (terminal 1)
cd backend
.\venv\Scripts\uvicorn app.main:app --reload        # http://127.0.0.1:8000

# 2. frontend (terminal 2)
cd frontend
python -m http.server 5173                           # http://127.0.0.1:5173
```

If the backend is not at `http://127.0.0.1:8000`, edit `js/config.js`.

## What you can see

Everything the API exposes, one page per table: users (admin), products, variants, plans,
taxes, discounts, quotation templates, subscriptions (+ lines), invoices (+ lines),
payments. The dashboard shows a live record count for every table. Click any row for the
full record; the products page also shows each product's variants and plans.

Menus and actions follow the signed-in role (admin / staff / customer), mirroring the
backend's permissions. The backend remains the source of truth for access control.

## Files

- `index.html` - page shell
- `css/styles.css` - styles (light and dark)
- `js/config.js` - API base URL
- `js/app.js` - API client, auth screens, views, forms
