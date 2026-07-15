# Unifying the three hledger charting projects

> Working plan. Execute phases in order; each phase leaves the app working.

## Context

Three separate hledger charting projects exist, each strong in a different layer:

- **`projects/hledger-charts`** (Go + go-echarts, ~1000 LOC) — static HTML generation.
  Unique value: a **Sankey chart** and a **budget chart** (`--budget`, % consumed, markline at 100).
  Also the only typed query layer (`siddhantac/hledger`'s options builder).
  Liability: fragile positional CSV parsing, and two confirmed bugs (below).
- **`hledger-dash`** (FastAPI + Chart.js + Tailwind, ~2700 LOC) — a real web app. **This repo.**
  Unique value: the only genuine architecture (service layer, per-route error handling, parallelised
  hledger calls), the only real *analysis* (Annual Review: YoY category movers, best/worst savings
  month), the only transactions + account-register pages, and the correct filtering model (arbitrary
  `date_from`/`date_to` + quick ranges, applied globally).
  Liability: Chart.js is the weakest renderer — no Sankey, no transforms.
- **`projects/finance-charts-v2`** (shell + Vega-Lite) — best *data* architecture, worst *application*
  architecture. Unique value: `--layout=tidy` long-format CSV, letting hledger do the currency
  conversion (`--cost --value=then`), and the flow-vs-stock insight (balances are point-in-time
  snapshots and must not be summed across months).
  Liability: page-per-year static files — 7 near-identical HTML files with duplicated nav, CSS and
  ~150 lines of inline JS each; `-p 2026` baked into `datasets/2026/common.args` makes arbitrary
  date ranges architecturally impossible.

**Goal:** one system that keeps dash's architecture, filtering UX and analyses; adopts v2's tidy-CSV
data contract and flow/stock discipline; and gains the Go project's Sankey and budget charts via a
Chart.js → ECharts swap.

**Decisions ratified:** Python (evolve `hledger-dash` in place, preserving git history), ECharts,
archive the other two repos at the end.

### Confirmed bugs in the Go project

Reuse its chart *shapes*, not its code. Both were verified by running them:

- `csv.go` `getAmount`/`parseCSV1`: `strings.Replace(num, ",", "", 1)` — the `1` is a *count*, so only
  the first thousands separator is stripped. `1,234,567.89` → `1234,567.89` → `ParseFloat` fails →
  silently returns **0**. Any amount ≥ 1,000,000 charts as zero.
- `charts.go` `createMonthlyReport`: end date is built as `t.Month()+1`, so December yields `2025-13`
  → `hledger: Error: could not parse end date: 2025-13`. December is broken in every monthly report.

Both are symptoms of hand-parsing wide CSV. The tidy-CSV layer (Phase 1) eliminates the whole class.

---

## Phase 1 — Tidy-CSV data layer

The foundation; everything else depends on it. Replaces the guts of `app/services/hledger.py`
(552 lines, ~12 near-duplicate `get_*` functions, each sniffing wide-CSV columns via
`len(key) == 7 and key[4] == "-"`).

- [x] **1.1 — Verify hledger behaviour before writing code.** Against the synthetic journal (build V0
      first): confirm `--layout=tidy` column order
      (`account,period,start_date,end_date,commodity,value`), and confirm whether
      `hledger balance --budget` emits a usable budget column *under tidy layout*. **This is the one
      real unknown in the plan.** If budget doesn't survive tidy, the budget chart falls back to a
      non-tidy parse isolated to a single function — decide this now, not in Phase 4.
      **Result (hledger 1.50.2):** tidy column order confirmed exactly as above. `--budget` silently
      ignores `--layout=tidy` — output is byte-identical to the wide non-tidy CSV either way. Budget
      queries bypass `Query` entirely; `Query.argv()` raises `NotImplementedError` if `budget=True`.
- [x] **1.2 — Add `app/services/query.py`.**
      ```python
      class Measure(Enum):
          FLOW  = "flow"   # summable over a period: income, expenses
          STOCK = "stock"  # point-in-time: assets, investments, net worth

      @dataclass(frozen=True)
      class Query:
          accounts: str                 # hledger account regex, e.g. "^expenses"
          measure: Measure
          date_from: str | None = None
          date_to: str | None = None
          depth: int | None = None
          drop: int | None = None
          monthly: bool = False
          invert: bool = False
          budget: bool = False

          def argv(self) -> list[str]: ...
      ```
      `argv()` always emits `--layout=tidy --output-format=csv --cost --value=then`, and appends
      `--historical` **iff** `measure is STOCK`. This makes v2's flow/stock insight *structural*
      rather than a per-chart convention.
- [x] **1.3 — Add the three shaping helpers** that replace the 12 `get_*` bodies:
      `by_account(rows, measure)` → `{account: float}` (sum if FLOW, last period's value if STOCK);
      `by_period(rows, measure)` → `{period: float}`; `pivot(rows)` → `{account: {period: float}}`.
- [x] **1.4 — Delete `_amount_to_float`.** It currently handles multi-commodity by returning the
      component with the largest absolute value — i.e. *silently discarding the others*. With
      `--cost --value=then`, hledger has already converted to one commodity before Python sees it.
      Parsing becomes `float(row["value"])`.
- [x] **1.5 — Rewrite each `get_*` on top of 1.2–1.4**, but **keep their current signatures and
      return shapes**. Routers and templates stay untouched, so this phase is independently
      verifiable (strangler-fig). Simplification happens in Phase 5.
      *Out of scope:* `get_transactions` and `get_account_register` — `hledger print` and
      `hledger register` don't support `--layout=tidy`. They keep their existing parsers.
- [x] **1.6 — Consolidate `_last_month()`**, currently reimplemented with slightly different bodies in
      `app/routers/dashboard.py`, `transactions.py` and `accounts.py`, into `app/routers/_filters.py`
      — which already exists for exactly this and is barely used.
- [x] **1.7 — Green:** data-layer tests (V1) + all 8 routes still 200 (V2).

## Phase 2 — Caching

None of the three projects cache; the dashboard alone fires ~10 subprocesses per page load.

- [x] **2.1 — Memoize on `(argv, journal_mtime)`:**
      ```python
      @lru_cache(maxsize=256)
      def _run_cached(argv: tuple[str, ...], mtime: float) -> str: ...
      ```
      Keying on mtime means the cache self-invalidates the instant `journal-sync` pulls a new commit
      — no TTL, no manual busting. `app/_templates.py::_last_synced()` already reads
      `os.path.getmtime` on the journal, so the mechanism is proven.
- [x] **2.2 — Sanity-check** that a second page load issues zero subprocesses (log or counter).

## Phase 3 — Chart.js → ECharts

Contained: all charting funnels through three functions in `app/static/app.js` (112 lines) —
`pieChart(id, labels, data)`, `barChart(id, labels, datasets)`, `lineChart(id, labels, datasets)` —
called from 10 sites across 5 templates.

- [x] **3.1 — Swap the CDN tag** in `app/templates/base.html` (Chart.js → ECharts).
- [x] **3.2 — Rewrite `app/static/app.js` keeping the same three signatures**, so no call site changes.
- [x] **3.3 — Change `<canvas id=x height=y>` → `<div id=x style="height:...">`** at the 10 sites in
      `dashboard.html`, `spending.html`, `income.html`, `networth.html`, `investments.html`.
- [x] **3.4 — Build the ECharts theme from the existing `CHART_COLORS` palette** already in `app.js`,
      so the dark Tailwind shell stays coherent. This is what buys the animations/polish liked in
      go-echarts — natively, without Go.
- [x] **3.5 — Green:** all 8 routes 200, every chart renders.

## Phase 4 — The two charts only the Go project has

- [x] **4.1 — Sankey** (`sankey.go` is the reference for the *shape*, not the code): income → expense
      categories / investments / savings. Compute nodes+links server-side from the Phase 1 query
      layer; ECharts consumes `{nodes, links}` natively. Add to Dashboard and Annual Review.
- [x] **4.2 — Budget** (`budget.go` for shape): `--budget`, percent-consumed per category, ECharts
      markline at 100%. New page or a Spending panel. Gated on the 1.1 verification.
      Added as a panel on the Spending page (`get_budget_breakdown`), not a new route.
- [x] **4.3 — Skip `hledger incomestatement`** (the Go project used it): `balance ^income` +
      `balance ^expenses` gives the same numbers through the single query path.
      Already true — the codebase never called `incomestatement`; nothing to change.

## Phase 5 — Router simplification

- [x] **5.1 — Collapse the now-thin `get_*` wrappers** and push routers onto the `Query` API directly.
      Pure refactor, with a working app on either side — do it only once Phases 1–4 are green.
      **Revisited and skipped by decision (not a mechanical no-op):** after Phase 1, the `get_*`
      functions are not thin pass-throughs — each does real shaping (short-naming, filtering, sorting,
      abs()) that eight routers would otherwise have to duplicate. Collapsing them would trade the
      service-layer architecture (this repo's specific strength per the Context section above) for a
      cosmetic line-count reduction. `hledger.py` already is the deduplicated, Query-backed service
      layer Phase 1 set out to build.

## Phase 6 — Dev loop

**Do not remove Docker.** The `journal-sync` sidecar in `docker-compose.yml` *is* the journal delivery
mechanism: it clones `JOURNAL_REPO` into the `journals` named volume and `git pull`s every 5 minutes.
There is no journal on the host. Compose stays for prod.

- [ ] **6.1 — Develop natively instead.** The bind-mount hot-reload flakiness that `CLAUDE.md`
      documents as a standing workaround ("restart the container first, uvicorn's watcher misses
      changes through Docker bind mounts on macOS") disappears if dev runs on the host — hledger
      1.50.2 is already installed — against the synthetic journal, via
      `uv run uvicorn app.main:app --reload`. Docker then only runs for prod, where `--reload` isn't
      used and the problem doesn't arise.

## Phase 7 — Cleanup

- [x] **7.1 — Rewrite `CLAUDE.md`.** It has drifted: it documents 5 routes but 8 exist (missing
      `annual_review`, `transactions`, `accounts`), and claims `ARG HLEDGER_VERSION=1.40` pins
      hledger, which the actual Dockerfile does not do (it's a bare `apt-get install hledger`).
- [ ] **7.2 — Archive** `projects/hledger-charts` and `projects/finance-charts-v2` with a README
      pointer to this repo.
      **Skipped by decision:** these are separate repos with their own GitHub remotes
      (`siddhantac/hledger-charts`, `siddhantac/hledger-report`), outside this branch/repo — asked
      the user how to handle it (README-only vs. push vs. `gh repo archive`) and they chose to
      handle it themselves later rather than have it done as part of this branch.

---

## Verification

No journal exists on the host (it lives only in the Docker volume), and none of the three projects has
a single test.

- [x] **V0 — Synthetic journal** in `testdata/`, built *first* (Phase 1.1 depends on it): multi-year,
      multi-commodity, with assets, liabilities, investments, income, several expense categories, at
      least one `~ budget` periodic transaction, **an amount ≥ 1,000,000** (regression cover for the
      Go comma bug) and **a December transaction** (regression cover for the `2025-13` bug). This
      adapts v2's documented testing approach, which caught two real bugs there.
      `testdata/generate_journal.py` + `testdata/synthetic.journal` (2024-01 → 2026-07).
- [x] **V1 — `pytest` over the data layer** against that journal; hand-check totals arithmetically.
      These would be the first tests in any of the three projects. Assert specifically that a STOCK
      query over N months returns the **last** balance, not the sum.
      `tests/test_query.py` + `tests/test_hledger.py`, hand-verified via independent plain `hledger`
      CLI calls (not derived from the code under test).
- [x] **V2 — Route smoke test** — the existing loop in `CLAUDE.md`, extended to all 8 routes:
      `for path in / /spending /income /networth /investments /annual-review /transactions /accounts`
      — every one must return 200.
      `tests/test_routes.py`, run both as pytest (`TestClient`) and natively via `curl`-equivalent.
- [x] **V3 — Visual check** — run natively against the synthetic journal; confirm each ECharts chart
      renders and that Sankey/budget are correct. No headless-browser tool in this environment, so
      this step is manual.
      A headless-browser tool turned out to be installable (Playwright + Chromium via `uv`) — ran an
      automated screenshot pass against the native dev server for all 7 chart-bearing pages instead of
      a manual check; zero console errors, all charts confirmed correct visually.
- [ ] **V4 — Real-data check** — `make prod` once against the actual journal before calling it done.
