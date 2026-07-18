# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
make dev-native  # uv run uvicorn --reload against testdata/synthetic.journal (for development)
make dev         # Docker with hot-reload — the only way to develop against the real journal,
                  # which lives only in the journal-sync volume, not on the host
make prod        # build + start production image
make down        # stop containers
make logs        # tail hledger-dash logs
make test        # uv run pytest against testdata/synthetic.journal
```

App available at http://localhost:8000 (Docker) or whatever port uvicorn picks for `dev-native`.

`uv sync` sets up `.venv` from `pyproject.toml`/`uv.lock`. Docker still installs from
`requirements.txt` directly (unchanged, kept in sync by hand with `pyproject.toml`'s
`dependencies`).

## Self-testing after changes

**Always run this after adding or modifying a page.** Prefer `make dev-native` — it doesn't have
the bind-mount hot-reload flakiness Docker has on macOS. If testing against Docker instead,
restart the container first (its file watcher can miss changes through the bind mount).

```bash
# Native (uv run uvicorn --reload, already picks up changes):
for path in / /spending /income /networth /investments /annual-review /transactions /accounts; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:<port>$path)
  echo "$code  $path"
done

# Docker:
docker restart hledger-dash-hledger-dash-1
for path in / /spending /income /networth /investments /annual-review /transactions /accounts; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000$path)
  echo "$code  $path"
done
docker logs hledger-dash-hledger-dash-1 --tail 50   # if any route isn't 200
```

Also run `make test` — `tests/test_routes.py` covers the same 8-route smoke check, plus
`tests/test_hledger.py`/`tests/test_query.py` cover the data layer against
`testdata/synthetic.journal` (hand-verified totals, so a wrong number fails a test, not just a
500).

Common causes of failures:
- **500**: Jinja2 template references a variable not passed from the router, or an unhandled exception escaped the `try/except` block.
- **404**: Router not registered in `app/main.py`, or uvicorn hasn't reloaded after a new file was added.
- **Import error on startup**: Syntax error in a Python file — check logs immediately after restart.

## Architecture

Single Python service: **FastAPI** backend with **Jinja2** server-rendered templates. No frontend build step — CSS via Tailwind CDN, charts via ECharts CDN.

```
app/
├── main.py              # App entry point, router registration, static files
├── _templates.py        # Shared Jinja2Templates instance with fmt/fmt_pct filters, last_synced()/version() globals
├── routers/
│   ├── _filters.py      # last_month()/last_12_from() shared by several routers
│   ├── dashboard.py     # GET /
│   ├── spending.py      # GET /spending
│   ├── income.py        # GET /income
│   ├── networth.py      # GET /networth
│   ├── investments.py   # GET /investments
│   ├── annual_review.py # GET /annual-review
│   ├── transactions.py  # GET /transactions
│   └── accounts.py      # GET /accounts (per-account register, bank-statement view)
├── services/
│   ├── query.py          # Tidy-CSV query layer: Measure, Query, by_account/by_period/pivot
│   └── hledger.py         # get_* functions built on query.py; all hledger CLI calls + caching
├── static/
│   └── app.js            # pieChart(), barChart(), lineChart(), sankeyChart(), budgetChart(), quickRange()
└── templates/
    ├── base.html         # Layout: dark sidebar nav + date-range filter in header
    └── *.html            # Page templates extending base.html
testdata/
├── generate_journal.py   # Regenerates synthetic.journal — re-run after editing it
└── synthetic.journal     # Multi-year, multi-commodity test journal (see tests/)
tests/
├── conftest.py            # Points HLEDGER_FILE at testdata/synthetic.journal
├── test_query.py          # Unit tests for the shaping helpers (no hledger process)
├── test_hledger.py        # Integration tests, hand-verified against plain hledger CLI output
├── test_caching.py        # Verifies run_hledger caching + invalidation
└── test_routes.py         # All 8 routes return 200, no error banner, Sankey/budget panels render
```

## Data flow

All data comes from shelling out to the `hledger` binary. `HLEDGER_FILE` env var points to the journal. All routers use `concurrent.futures.ThreadPoolExecutor` to parallelise independent hledger calls. `run_hledger()` is memoized via `lru_cache` keyed on `(argv, journal_mtime)` — a second identical call issues zero subprocesses, and the cache self-invalidates the instant the journal file's mtime changes (e.g. `journal-sync` pulling a new commit).

### Query layer (`app/services/query.py`)

Almost every `hledger.py` function is built on `Query`, a typed wrapper around `hledger balance --layout=tidy --output-format=csv --cost --value=then`. Tidy layout means Python always parses the same six columns (`account,period,start_date,end_date,commodity,value`), and `--cost --value=then` means hledger has already converted every posting to one commodity before Python sees it — no hand-rolled multi-commodity parsing.

`Measure.FLOW` vs `Measure.STOCK` is structural, not a per-call convention:
- **FLOW** (income, expenses — summable over a period): `Query.argv()` does *not* add `--historical`.
- **STOCK** (assets, investments, net worth — point-in-time balances): `Query.argv()` *always* adds `--historical`. A stock measure can never accidentally be summed across months by a caller that forgot the flag.

Three shaping helpers turn tidy rows into what routers need:
- `by_account(rows, measure)` → `{account: float}` — sums periods for FLOW, keeps only the **last** period's value for STOCK.
- `by_period(rows, measure)` → `{period: float}`, summed across accounts.
- `pivot(rows)` → `{account: {period: float}}`.

**`Query` does not support `--budget`.** Verified against hledger 1.50.2: `--budget` silently ignores `--layout=tidy` and always emits the wide actual/budget paired-column CSV instead. `Query(..., budget=True).argv()` raises `NotImplementedError` rather than risk misparsing that shape as tidy rows — `get_budget_breakdown` uses its own dedicated non-tidy parser instead.

`get_transactions` (`hledger print`) and `get_account_register` (`hledger register`) don't go through `Query` — those hledger subcommands don't support `--layout=tidy`, so they keep their own CSV parsers.

Key functions in `app/services/hledger.py`:
- `run_hledger(*args)` — cached subprocess wrapper
- `available_years()` — scans journal for all years with data
- `months_in_range(date_from, date_to)` — list of YYYY-MM strings
- `get_summary(date_from, date_to)` — total income, expenses, net, savings_rate
- `get_expense_breakdown / get_income_breakdown` — depth-2 balance for pie charts
- `get_expense_category_history` — monthly spend per category (all time)
- `get_net_worth_history / get_net_worth_snapshot` — net worth over time and as-of snapshot
- `get_investment_breakdown / get_monthly_investment_total` — investment sub-account data
- `get_asset_breakdown / get_liability_breakdown` — depth-2 balance as-of a month
- `get_transactions` — flat list of transactions in a date range, most-recent first
- `get_account_list` — depth-2 asset/liability account names, split into `{"assets": [...], "liabilities": [...]}`
- `get_account_register(account, date_from, date_to)` — bank-statement view (date, description, amount, running balance) for one account, most-recent first
- `get_sankey_data(date_from, date_to)` — `{nodes, links}` for the money-flow Sankey: income sources → "Income" hub → expense categories / investments / savings
- `get_budget_breakdown(date_from, date_to, depth=2)` — `[{account, full_account, actual, budget, pct}]` from the journal's `~` periodic budget transactions, sorted most-over-budget first

## Date filtering

All routes (except Net Worth and Investments) accept `?date_from=YYYY-MM&date_to=YYYY-MM` GET params. Default is YTD, except **Accounts** and **Transactions**, which default to Last Month. The header in `base.html` renders the date inputs and quick-range buttons (YTD, Last Month, Last Year, All Time). Pass `first_month` from each router for the All Time button. `last_month()`/`last_12_from()` in `app/routers/_filters.py` are shared by dashboard/income/transactions/accounts rather than each reimplementing them.

The **Accounts** page also takes `?account=<name>` to pick which account's register to show (defaults to the first asset account); account pills are rendered from `get_account_list()`.

## Adding a new page

1. Add a router in `app/routers/your_page.py` — fetch data from `hledger.py`, return a `TemplateResponse` with all variables the template needs initialised before the `try` block.
2. Add `app/templates/your_page.html` extending `base.html`.
3. Register the router in `app/main.py`.
4. Add a nav link in `app/templates/base.html`.
5. **Run the self-test above.** If the new page needs a data shape the synthetic journal doesn't exercise, extend `testdata/generate_journal.py` and re-run it, and add a hand-verified assertion to `tests/test_hledger.py`.

## Chart helpers (app/static/app.js)

All charts are ECharts (`echarts.init()` against a sized `<div>`, not `<canvas>`). Dark theme is built from the `CHART_COLORS` palette at the top of the file.

- `pieChart(elId, labels, data)`
- `barChart(elId, labels, datasets)`
- `lineChart(elId, labels, datasets)` — pass `fill: false` in a dataset to disable area fill
- `sankeyChart(elId, nodes, links)` — `nodes`/`links` come straight from `get_sankey_data`
- `budgetChart(elId, rows)` — horizontal percent-consumed bars with a markLine at 100%; `rows` come straight from `get_budget_breakdown`
- `quickRange(range)` — sets date inputs and submits the filter form; ranges: `ytd`, `lastmonth`, `lastyear`, `alltime`

## hledger version

Not pinned. The Dockerfile installs whatever `apt-get install hledger` resolves to at build time. Native dev uses whatever `hledger` is on `$PATH` (developed against 1.50.2).

## App version display

The sidebar footer (`base.html`, next to "Synced ... ago") shows the running app version via the
`version()` template global in `app/_templates.py`. Resolution order: the `APP_VERSION` env var if
set, else `git describe --tags --always --dirty` run against the working directory, else
`"unknown"`. Result is memoized for the life of the process.

`git describe` needs a `.git` dir and the `git` binary, neither of which the production image has
(the Dockerfile only `COPY`s `app/`), so `make dev`/`make prod` compute `APP_VERSION` once via
`git describe` in the Makefile and pass it through `docker-compose.yml`'s `environment:` block.
`make dev-native` needs no such plumbing — it runs directly in the repo, so the `git describe`
fallback works as-is.

## Keeping this file updated

**Always update CLAUDE.md in the same change** whenever you add/remove a page, router, or `hledger.py` function, or change shared conventions (date filtering, self-test routes, directory layout). Treat a stale CLAUDE.md as a bug: check it against the actual routers/services before finishing any task that touches architecture.
