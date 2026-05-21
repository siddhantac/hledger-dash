# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
make dev    # build + start with hot-reload (for development)
make prod   # build + start production image
make down   # stop containers
make logs   # tail hledger-dash logs
```

App available at http://localhost:8000.

## Self-testing after changes

**Always run this after adding or modifying a page.** Uvicorn's file watcher can miss changes through Docker bind mounts on macOS — restart the container first, then check every route.

```bash
# 1. Restart to pick up any file changes uvicorn missed
docker restart hledger-dash-hledger-dash-1

# 2. Check HTTP status of all routes (all must be 200)
for path in / /spending /income /networth /investments; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000$path)
  echo "$code  $path"
done

# 3. If any route is not 200, check the logs
docker logs hledger-dash-hledger-dash-1 --tail 50
```

Common causes of failures:
- **500**: Jinja2 template references a variable not passed from the router, or an unhandled exception escaped the `try/except` block.
- **404**: Router not registered in `app/main.py`, or uvicorn hasn't reloaded after a new file was added.
- **Import error on startup**: Syntax error in a Python file — check `docker logs` immediately after restart.

## Architecture

Single Python service: **FastAPI** backend with **Jinja2** server-rendered templates. No frontend build step — CSS via Tailwind CDN, charts via Chart.js CDN.

```
app/
├── main.py              # App entry point, router registration, static files
├── _templates.py        # Shared Jinja2Templates instance with fmt/fmt_pct filters
├── routers/
│   ├── _filters.py      # Date-range normalisation helper
│   ├── dashboard.py     # GET /
│   ├── spending.py      # GET /spending
│   ├── income.py        # GET /income
│   ├── networth.py      # GET /networth
│   └── investments.py   # GET /investments
├── services/
│   └── hledger.py       # All hledger CLI calls via subprocess; parse CSV output
├── static/
│   └── app.js           # pieChart(), barChart(), lineChart(), quickRange()
└── templates/
    ├── base.html        # Layout: dark sidebar nav + date-range filter in header
    └── *.html           # Page templates extending base.html
```

## Data flow

All data comes from shelling out to the `hledger` binary. `HLEDGER_FILE` env var points to the journal. All routers use `concurrent.futures.ThreadPoolExecutor` to parallelise independent hledger calls.

Key functions in `app/services/hledger.py`:
- `run_hledger(*args)` — base subprocess wrapper
- `available_years()` — scans journal for all years with data
- `months_in_range(date_from, date_to)` — list of YYYY-MM strings
- `get_summary(date_from, date_to)` — total income, expenses, net, savings_rate
- `get_expense_breakdown / get_income_breakdown` — depth-2 balance for pie charts
- `get_expense_category_history` — monthly spend per category (all time)
- `get_net_worth_history / get_net_worth_snapshot` — net worth over time and as-of snapshot
- `get_investment_breakdown / get_monthly_investment_total` — investment sub-account data

## Date filtering

All routes (except Net Worth and Investments) accept `?date_from=YYYY-MM&date_to=YYYY-MM` GET params. Default is YTD. The header in `base.html` renders the date inputs and quick-range buttons (YTD, Last Month, Last Year, All Time). Pass `first_month` from each router for the All Time button.

## Adding a new page

1. Add a router in `app/routers/your_page.py` — fetch data from `hledger.py`, return a `TemplateResponse` with all variables the template needs initialised before the `try` block.
2. Add `app/templates/your_page.html` extending `base.html`.
3. Register the router in `app/main.py`.
4. Add a nav link in `app/templates/base.html`.
5. **Run the self-test above.**

## Chart helpers (app/static/app.js)

- `pieChart(canvasId, labels, data)`
- `barChart(canvasId, labels, datasets)`
- `lineChart(canvasId, labels, datasets)` — pass `fill: false` in a dataset to disable area fill
- `quickRange(range)` — sets date inputs and submits the filter form; ranges: `ytd`, `lastmonth`, `lastyear`, `alltime`

## hledger version

Pinned via `ARG HLEDGER_VERSION=1.40` in the Dockerfile. Update this arg to upgrade.
