# Cold-load performance: root cause and options

> Working notes. `/networth` and other pages take up to ~10s on first load against the real
> journal, then become instant. This document records why, and the options considered to fix it.

## Root cause

The real journal (`finances.journal`, includes six years of statements, ~17K lines, 5MB) is slow
for `hledger` to parse — and **every single `hledger` invocation costs the same ~1.8-2.2s
regardless of how narrow the query is**, because hledger always parses and balance-validates the
*entire* journal into an in-memory model before applying any filter. There's no filter-pushdown.

Benchmarked directly against the real journal:

| Command | Time |
|---|---|
| `hledger print` (bare parse, discard output) | 2.26s |
| `hledger balance --layout=tidy --output-format=csv` (no valuation) | 1.78s |
| `hledger balance --layout=tidy --output-format=csv --cost --value=then` (what the app uses) | 1.80s |
| Same, narrowed to 1 account + 1 month | 2.15s — **narrowness doesn't help** |
| Same, against a flattened single-file journal (`hledger print -x` → one file) | 1.71s — **file count/include-chain isn't the bottleneck; parsing the data volume is** |
| `hledger --version` / `hledger help` (process spawn only, no journal read) | ~0.03-0.04s — **spawn overhead is negligible** |

Live page timings (via the running `make dev-native` server against the real journal):

| Page | First hit (cold cache) | Second hit (same page, warm cache) |
|---|---|---|
| `/networth` | 10.5s | 0.03s |
| `/investments` | 2.8s | 0.02s |

Each page fires 7-10 separate `hledger balance` calls in parallel
(`concurrent.futures.ThreadPoolExecutor`, see `app/services/hledger.py`), each with a distinct
`argv` (different account regex / date range / depth). `_run_cached` (`app/services/hledger.py`,
an `lru_cache` keyed on `(argv, journal_mtime)`) makes an exact-repeat request instant, but a new
argv combination — a different page, or the same page with a different date range — always pays
the full ~2s parse cost again. That's why first load is slow and repeat loads of the *same* view
are fast, while a new page or a new date range is slow again.

## Options considered

### A — Master pull + in-memory Python aggregation
Replace the current pattern (N narrow `hledger balance` calls per page, each independently cached
by exact argv) with 1-2 *maximal* pulls — full account tree, full date range, monthly
granularity, tidy CSV, one FLOW and one STOCK query — done once per journal-mtime-change and
cached exactly like today. Every `get_*` function (`by_account`/`by_period`/`pivot` in
`app/services/query.py`) then slices/aggregates that in-memory dataset in pure Python
(account-regex → prefix match, depth → truncate+sum, date range → dict slice) instead of shelling
out again.

- **Pros:** Cuts total hledger cost from ~7-10 × 2s down to 1-2 × 2s, and that cost is shared
  across every page and every date range, not paid per-page/per-argv. Keeps hledger doing the
  currency conversion (`--cost --value=then`) — the risky part — so no reimplementation of
  valuation logic.
- **Cons:** Moderate refactor of `query.py`'s shaping helpers and `hledger.py`'s `get_*` bodies.
  `hledger print`/`register` (transactions, accounts pages) and `--budget` (non-tidy) don't fit
  this model and keep their current per-call caching — already cheap (1-2 calls each).
- **Effort:** Moderate. Routers/templates untouched (strangler-fig, same pattern as the original
  Phase 1 tidy-CSV migration in `PLAN.md`).
- **Status:** **Implemented** on `perf/master-pull-aggregation`, on top of the Option D research
  spike below (see "Option A — implementation notes").

### B — Background pre-warm on startup / after journal changes
Fire the master queries (or all known page queries) in a background task right after the app
starts and whenever journal mtime changes, so the cache is warm before a real request lands.

- **Pros:** Cheap, additive on top of any other option. Moves the cost off the user's first click.
- **Cons:** Doesn't reduce total work, just relocates it. Can't pre-warm arbitrary custom date
  ranges a user types in.
- **Effort:** Low.
- **Status:** Not started — deferred, to be explored together with A.

### C — Consolidate calls per-page without full in-memory redesign
A lighter, per-request version of A: each page fires 1-2 broad queries instead of 7-10 narrow
ones, aggregates in Python for that request only — no cross-page/cross-date-range sharing.

- **Pros:** Simpler than A.
- **Cons:** A different date range on repeat visits still re-pays the full ~2s cost — doesn't fix
  "first time I pick a custom range" slowness the way A does.
- **Effort:** Low-moderate.
- **Status:** Not pursued — superseded by A, which solves the same problem more completely for
  only moderately more work.

### D — Persistent `hledger-web --serve-api` sidecar
Stop shelling out to the `hledger` CLI per query. Run `hledger-web --serve-api` as a persistent
process — it loads the journal once and file-watches for changes — and have the FastAPI app query
its JSON API over HTTP instead of spawning `hledger` subprocesses.

- **Pros (as originally framed):** If the API exposes report-shaped data, every query (not just
  cache-hit repeats) becomes fast, since the parse happens once inside the long-running process
  rather than per-call. No caching architecture needed in our app at all.
- **Cons / open questions (as originally framed):** Unverified whether the JSON API supports the
  tidy-report shape (`--layout=tidy`, `--historical`, `--budget`) `Query.argv()` relies on. Adds a
  second process to run/supervise in both `make dev-native` and Docker prod.
- **Effort:** Unknown until researched.
- **Status:** **Research spike in progress this session** — see findings below.

---

## Option D — research findings

Environment: `hledger-web 1.50.2` is already installed alongside `hledger 1.50.2`.
`hledger-web --serve-api --allow=view` serves a read-only JSON API without the web UI, on
`127.0.0.1` by default (no external exposure).

### The core premise holds — and holds well

hledger-web parses the journal once at process startup and serves every subsequent request from
that in-memory model, no matter how large the response:

| Request | Time |
|---|---|
| `/version`, `/accountnames`, `/accounts` (small payloads) | 20-40ms, first request and every repeat |
| `/transactions` (full 6-year history, 18MB JSON, 12,346 transactions), server + network | ~350ms, first request and every repeat |
| `/transactions`, fetched **and JSON-parsed in Python** (`urllib` + `json.loads`) | fetch 0.36-0.37s + parse 0.19-0.23s ≈ **0.56-0.6s total, one-time** |
| Same call repeated | same ~0.6s — no caching needed on our side, the server itself never re-parses |

Compare to the CLI: **every single `hledger` invocation costs ~1.8-2.2s**, cold or warm, narrow
or broad (see root-cause table above). Pulling hledger-web's *entire* transaction history into
Python is faster than one single narrow CLI query, and it's a **one-time cost per journal change**,
not per query. This directly validates Option D's central premise.

Confirmed hledger-web also **auto-reloads on file change without a restart** (tested: appended a
transaction to a scratch copy of the journal, re-queried without restarting the server — the new
transaction appeared, request still fast). This matches the `journal-sync` 5-minute-pull
requirement for free.

### The routes are raw data dumps, not pre-computed reports — revise the original framing

Per `man hledger-web`, the documented JSON routes are:

```
/version  /accountnames  /transactions  /prices  /commodities  /accounts  /accounttransactions/ACCOUNTNAME
```

Tested empirically against the real journal:

- **None of them accept query-string filters.** Tried `?depth=`, `?value=`, `?period=`,
  `?cost=`, `?startDate=`, `?begin=` against `/accounts` and `/transactions` — identical
  byte-for-byte output (same size, same md5) regardless of params. Whatever CLI-flag filtering
  hledger-web's *web UI* supports, the bare JSON routes ignore it entirely.
- **`/accounts` is a single all-time snapshot**, not a period-bucketed report — its
  `adata.pdperiods` array has exactly one entry (key `"0000-01-01"`), a cumulative total across
  all of history, not "balance as of today" or "balance per month." Not directly usable for
  either FLOW or STOCK measures as currently defined.
- **`/transactions` is the useful one**: the full raw posting-level ledger (equivalent to
  `hledger print` as JSON) — every transaction, every posting, with dates and amounts. Amounts
  are technically still a list (`MixedAmount`), but each element carries a convenient
  `aquantity.floatingPoint` field — no need to hand-roll the `decimalMantissa`/`decimalPlaces`
  math.
- So this **is not "pre-computed reports for free."** To get what `Query`/`app/services/query.py`
  currently produces (FLOW sums by account/period, STOCK point-in-time balances, depth rollups,
  account-regex filtering, arbitrary date ranges), Python would have to do all of that shaping
  itself over the raw `/transactions` dump — i.e., the same in-memory-aggregation architecture as
  **Option A**, just sourced from hledger-web's live JSON instead of our own periodic CLI pulls.

### The valuation risk — resolved better than expected

The one thing Option A doesn't need to worry about (letting the CLI's `--cost --value=then` do
currency conversion) looked like a real risk for D at first: a `/transactions` pull *without*
startup flags returns **raw multi-commodity `MixedAmount` lists with embedded per-lot cost basis**
(`acost.contents`) — exactly the hand-rolled-multi-commodity-parsing hazard `PLAN.md` Phase 1.4
deliberately eliminated (deleting `_amount_to_float`, which used to silently pick the
largest-absolute-value commodity and discard the rest).

**But this turned out to be solvable, not a dead end.** `hledger-web` accepts the same general
report flags as the CLI (`-B/--cost`, `--value=WHEN`, `--depth`, etc. — confirmed in
`hledger-web --help`), applied **once at server startup**, not per-request. Restarting the spike
server with `--cost --value=then` baked in:

- `/accounts` amounts collapsed from a multi-commodity list-with-cost-lots to a single
  already-converted `{"acommodity": "SGD$", "aquantity": {"floatingPoint": 247.32...}}`.
  `/transactions` postings did the same — single-commodity, already-valued amounts.
- Fetch+parse timing was unaffected (~0.4-0.85s total, same ballpark as unvalued).

So hledger itself still does the currency conversion — we just ask for it once at process launch
instead of once per CLI call. **This removes the main new risk Option D would otherwise add over
Option A.**

### Remaining real difference from Option A

Even with valuation solved, `/accounts`' single all-time-cumulative snapshot means STOCK measures
(point-in-time balances) still have to be derived by Python computing a **running balance from the
raw `/transactions` postings**, sorted by date — logic Option A doesn't need, because a CLI
`balance --historical --monthly` pull already returns per-month point-in-time balances directly.
This is a real, if modest, amount of *additional* aggregation logic (a cumulative-sum pass) that
Option D requires and Option A doesn't.

### Process/security notes

- `--allow=view` runs it read-only (no `/add` mutation risk) — appropriate for this app.
- Binds to `127.0.0.1` by default; no change needed to expose it beyond localhost.
- Needs supervising as a long-running sidecar in both `make dev-native` and Docker prod. Precedent
  exists for the latter: `docker-compose.yml` already runs a `journal-sync` sidecar, so adding a
  second sidecar service follows an established pattern rather than introducing a new one.

### Verdict

The "persistent process avoids re-parsing" premise is **real and strong** — fetching the entire
6-year transaction history through hledger-web (~0.6s, one-time, auto-refreshing on journal
change) beats even a single narrow CLI call (~2s, paid on every new argv). But the JSON API is
**not** a source of pre-computed reports — it's a fast, always-fresh, already-valued raw
transaction feed. In practice, **Option D converges to Option A's architecture** (pull once,
aggregate in Python, cache the result) — with three differences from doing Option A via the CLI
directly:

1. **Faster and simpler master pull** — one HTTP GET instead of coordinating 1-2 CLI `Query`
   calls, and hledger-web does the file-watching/reload for us instead of us tracking mtime
   ourselves (though we'd likely still want our own `lru_cache`-style layer on top, to avoid
   re-fetching+re-parsing 18MB of JSON on every request).
2. **One extra aggregation step Option A avoids**: STOCK (point-in-time) balances require a
   Python-side running-balance computation over raw postings, since hledger-web has no
   `--historical`-equivalent report route. Option A gets this for free from the CLI's own
   `--historical` balance report.
3. **One extra process to run and supervise**, in both dev and Docker prod — a real ongoing cost
   Option A doesn't have (Option A only ever shells out to the same `hledger` CLI already used
   today, just less often).

**Recommendation:** Option D is viable and its core hypothesis is validated, but it is now
understood to be a strictly larger version of Option A's work (same Python aggregation layer,
plus a running-balance pass, plus a sidecar process to run) for a benefit that's only marginal
over Option A alone (both eliminate the current N-calls-per-page problem; D's master pull is
somewhat faster and self-refreshing, but Option A's is simpler and adds no new process). Suggest
building **Option A first** since it's already scoped and lower-risk; revisit D afterward only if
Option A's periodic CLI master-pull cost (~2-4s per journal change) turns out to be a problem in
practice — at which point D's ~0.6s pull becomes the natural upgrade path, reusing the same
Python-side aggregation code Option A will have already built.

---

## Option A — implementation notes

Implemented on `perf/master-pull-aggregation`. `master_rows(measure)` (`app/services/hledger.py`)
fetches exactly 2 unrestricted, full-history, `--monthly` pulls total (one FLOW, one STOCK),
memoized on `(measure, journal_mtime)` on top of `run_hledger`'s existing subprocess-level cache.
Every `get_*` function now calls `slice_rows()` (`app/services/query.py`) to filter/depth-truncate/
date-window that in-memory dataset in Python instead of shelling out again. Confirmed end-to-end
against the synthetic journal: 12 `get_*` calls spanning 6 distinct date ranges cost **2** hledger
subprocess invocations total (was up to 12, one per distinct argv, under the old per-call cache).

### Accuracy strategy

Before touching any `get_*` function, a differential test matrix compared the OLD path (real
`hledger` CLI call per narrow query) against the NEW path (`slice_rows` over the cached master
pull) across all 17 real (account pattern, depth, monthly, date range) combinations found in
`hledger.py`, plus deliberate edge cases (depth deeper than any real account, a zero-transaction
date range, a range spanning a year boundary, etc.) — see the "What I verified empirically" section
of the approved plan for the full list. Only once that matrix was green did `get_*` functions get
swapped one group at a time, each followed by the full test suite — critically, `tests/
test_hledger.py`'s hand-verified assertions (independently computed against raw `hledger` CLI
output, not derived from either implementation) had to keep passing **unmodified** throughout, so a
bug shared by both code paths couldn't slip through the differential matrix alone. All 48 tests
pass; the temporary differential-test file was deleted once its job was done, with its durable
edge-case coverage folded into `tests/test_query.py` as permanent `slice_rows` unit tests.

### The one real edge case found

hledger's own multi-period `--monthly` reports emit an explicit `"0"` row for any account that has
nonzero activity *somewhere* in the full journal but not within a given sub-window (to keep the
table rectangular) — e.g. `income:investment_gains` (one $1.2M transaction in 2025-06) shows up
with a `0` row in every *other* month of a full-history master pull. A real narrower per-page
hledger call scoped to just that window would never have produced that account at all. `slice_rows`
replicates hledger's own suppression: an account with zero activity across the *entire* selected
window is dropped entirely, but an account with even one nonzero row in-window keeps all its rows,
including trailing zeros — needed so a STOCK "last period" pick correctly reflects a balance that
was genuinely paid off/closed mid-window, rather than falling back to a stale earlier nonzero value.

### What's left

Real-journal timing re-check (cold `/networth` load, was ~10s) is a manual step deferred to the
user, same as the existing "V4 real-data check" convention in this repo's history — the synthetic
journal is too small to reproduce the original ~2s-per-call cost that motivated this work.
