# Syriana Energy: full-stack E2E suite

Python + Playwright (Chromium) + pytest. It drives the **real** stack: Next.js frontend (:3000) proxying to the FastAPI backend, Postgres, Redis and the worker. No mocks.

Each UI test runs in 4 combinations: `ar`/`en` x desktop (1280px) / mobile (390px). Strings are looked up from `frontend/messages/<locale>.json`, so the suite is locale-agnostic. A test also fails on any uncaught page error, `console.error` (hydration etc.) or HTTP 5xx.

## Prerequisites
```bash
# backend (fresh DB), see backend/ README
cd backend && alembic upgrade head
python -m app.cli seed-plans
python -m app.cli create-superadmin --email admin@syriana.energy --password 'Admin12345!'
python -m app.cli seed-demo --speed 240 --backfill-hours 24
REGISTER_RATE_LIMIT=100000 REDIS_URL=redis://localhost:6379/0 uvicorn app.main:app --port 8100 &
# (the suite registers many users from one IP; the default signup limit is 30/hour/IP)
python -m app.worker &                  # required for live data + alerts
# frontend (BACKEND_URL is baked in at build time)
cd frontend && npm ci && BACKEND_URL=http://localhost:8100 npm run build && PORT=3000 npm start &
```
The assistant test assumes `ANTHROPIC_API_KEY` is NOT set on the backend.

## Run
```bash
pip install -r e2e/requirements.txt          # playwright browsers: set PLAYWRIGHT_BROWSERS_PATH, do not re-download
cd e2e
python -m pytest -q                          # everything (about 10 min)
python -m pytest -q -k "ar-mobile"           # one locale/viewport
python -m pytest -q test_api.py              # API/security/white-label only
E2E_WEB=http://localhost:3000 python -m pytest -q
```
Screenshots of key pages are written to `e2e/screens/`.
