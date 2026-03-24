# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

**With Docker (recommended):**
```bash
cp .env.example .env
# Edit .env to set JOURNAL_DIR and JOURNAL_FILE
docker compose up --build
# App available at http://localhost:8000
```

**Locally (for development):**
```bash
pip install -r requirements.txt
export HLEDGER_FILE=/path/to/your/main.journal
uvicorn app.main:app --reload
```

## Architecture

Single Python service: **FastAPI** backend with **Jinja2** server-rendered templates. No frontend build step — CSS via Tailwind CDN, charts via Chart.js CDN.

```
app/
├── main.py              # App entry point, router registration, static files
├── routers/
│   ├── _filters.py      # Shared year/month filter context builder (used by all routers)
│   ├── dashboard.py     # GET / — summary cards + monthly bar chart
│   ├── expenses.py      # GET /expenses — pie chart + top expenses table
│   ├── income.py        # GET /income — pie + breakdown table + trend line
│   └── reports.py       # GET /reports — income statement + balance sheet (raw hledger text)
├── services/
│   └── hledger.py       # All hledger CLI calls via subprocess; parse CSV output
└── templates/
    ├── base.html        # Layout: dark sidebar nav + year/month filter dropdowns in header
    └── *.html           # Page templates extending base.html
```

## Data flow

All data comes from shelling out to the `hledger` binary. `HLEDGER_FILE` env var points to the journal. Key functions in `app/services/hledger.py`:

- `run_hledger(*args)` — base subprocess wrapper
- `available_years()` — scans journal for all years (used to populate the year dropdown)
- `get_monthly_totals(year, account_query)` — monthly CSV balance for bar/line charts
- `get_expense_breakdown(year, month)` / `get_income_breakdown(...)` — depth-2 balance for pie charts
- `get_summary(year, month)` — total income, expenses, net for a period
- `get_income_statement` / `get_balance_sheet` — raw text reports

## Year/month filtering

All routes accept `?year=YYYY&month=M` GET params (month=0 means full year). `_filters.py:filter_context()` normalises these and provides `available_years` and `months` lists needed by `base.html` to render the dropdowns.

## Adding a new page

1. Add a router in `app/routers/your_page.py` — call `filter_context()`, fetch data from `hledger.py`, return a `TemplateResponse`
2. Add `app/templates/your_page.html` extending `base.html`
3. Register the router in `app/main.py`
4. Add a nav link in `app/templates/base.html`

## Chart helpers (app/static/app.js)

Three global functions: `pieChart(canvasId, labels, data)`, `barChart(canvasId, labels, datasets)`, `lineChart(canvasId, labels, datasets)`. Pass data via Jinja2 `| tojson` filter in `{% block scripts %}`.

## hledger version

Pinned via `ARG HLEDGER_VERSION=1.40` in the Dockerfile. Update this arg to upgrade.
