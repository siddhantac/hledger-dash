import csv
import io
import logging
import os
import subprocess
from datetime import date
from functools import lru_cache

from app.services.query import Measure, by_account, by_period, pivot, slice_rows

logger = logging.getLogger(__name__)


def _journal_file() -> str:
    path = os.environ.get("HLEDGER_FILE", "")
    if not path:
        raise RuntimeError("HLEDGER_FILE environment variable is not set")
    return path


@lru_cache(maxsize=256)
def _run_cached(argv: tuple[str, ...], mtime: float) -> str:
    # mtime is part of the cache key only, to invalidate on journal changes.
    cmd = ["hledger", "-f", _journal_file(), *argv]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Command failed: %s\nstderr: %s", " ".join(cmd), result.stderr.strip())
        raise RuntimeError(f"hledger error: {result.stderr.strip()}")
    return result.stdout


def run_hledger(*args: str) -> str:
    # Keying on the journal's mtime means the cache self-invalidates the
    # instant journal-sync pulls a new commit — no TTL, no manual busting.
    mtime = os.path.getmtime(_journal_file())
    return _run_cached(args, mtime)


def _next_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def _period_arg(date_from: str, date_to: str) -> str:
    if date_from == date_to:
        return date_from
    return f"{date_from}..{_next_month(date_to)}"


def _parse_csv(output: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(output))
    return [row for row in reader]


def _parse_single_amount(s: str) -> float:
    """Parse one commodity amount like '1,234.56 SGD$' or 'BTC 0.001'."""
    cleaned = s.replace(",", "").strip()
    for part in cleaned.split():
        try:
            return float(part)
        except ValueError:
            continue
    return 0.0


@lru_cache(maxsize=8)
def _master_rows_cached(measure: Measure, mtime: float, today: str) -> list[dict]:
    argv = ["balance", "--layout=tidy", "--output-format=csv", "--cost", "--value=then", "--monthly"]
    if measure is Measure.STOCK:
        # An unrestricted balance report only ever covers periods that
        # actually have transactions, with no carry-forward past the last
        # one — but a STOCK balance is a running total, so a month with no
        # new postings (e.g. this month's statements haven't been logged
        # yet) still has a real, unchanged balance. Explicitly bounding the
        # period through today forces hledger to forward-fill --historical
        # balances through the current month, matching what an explicit
        # per-call --period request used to do before the master-pull
        # refactor. today is part of the cache key so this rolls over daily.
        argv += ["--historical", "--period", f"..{_next_month(today)}"]
    return _parse_csv(run_hledger(*argv))


def master_rows(measure: Measure) -> list[dict]:
    """
    One unrestricted, full-history, monthly pull per measure — cached on
    journal mtime (and, for STOCK, on today's date — see _master_rows_cached)
    like run_hledger, so every get_* call for any account pattern/depth/
    date-range shares the same 2 subprocess invocations instead of paying its
    own ~2s hledger parse cost.
    """
    mtime = os.path.getmtime(_journal_file())
    today = date.today().strftime("%Y-%m")
    return _master_rows_cached(measure, mtime, today)


def _short_name(account: str) -> str:
    return account.split(":")[-1] if ":" in account else account


def months_in_range(date_from: str, date_to: str) -> list[str]:
    result = []
    y, m = int(date_from[:4]), int(date_from[5:7])
    end_y, end_m = int(date_to[:4]), int(date_to[5:7])
    while (y, m) <= (end_y, end_m):
        result.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def available_years() -> list[int]:
    """Return sorted list of years that have journal entries."""
    output = run_hledger(
        "balance", "assets",
        "--yearly", "--output-format", "csv", "--no-total",
    )
    rows = _parse_csv(output)
    years: set[int] = set()
    for row in rows:
        for key in row.keys():
            key = key.strip()
            if len(key) == 4 and key.isdigit():
                years.add(int(key))
    today_year = date.today().year
    return [y for y in sorted(years) if y <= today_year]


# ── Spending ───────────────────────────────────────────────────────────────

def get_expense_category_history(date_from: str, date_to: str, depth: int = 2) -> dict[str, dict[str, float]]:
    """
    Monthly spend per top-level category across date range.
    Returns {short_category_name: {YYYY-MM: amount}}.
    One hledger call; caller derives heat map, quarterly rollup, and trend from this.
    """
    rows = slice_rows(master_rows(Measure.FLOW), accounts="expenses", depth=depth, date_from=date_from, date_to=date_to)
    by_full_account = pivot(rows)
    result: dict[str, dict[str, float]] = {}
    for account, monthly in by_full_account.items():
        monthly = {m: abs(v) for m, v in monthly.items()}
        if any(v > 0 for v in monthly.values()):
            result[_short_name(account)] = monthly
    return result


def get_monthly_expense_totals(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly expense totals: {YYYY-MM: float}."""
    rows = slice_rows(master_rows(Measure.FLOW), accounts="expenses", date_from=date_from, date_to=date_to)
    months = months_in_range(date_from, date_to)
    period_totals = by_period(rows, Measure.FLOW)
    return {m: abs(period_totals.get(m, 0.0)) for m in months}


def get_expense_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """Expense totals by category: [{account, full_account, amount}] sorted desc."""
    rows = slice_rows(master_rows(Measure.FLOW), accounts="expenses", depth=depth, date_from=date_from, date_to=date_to)
    results = []
    for account, amount in by_account(rows, Measure.FLOW).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_expense_total(date_from: str, date_to: str) -> float:
    rows = slice_rows(master_rows(Measure.FLOW), accounts="expenses", date_from=date_from, date_to=date_to)
    return abs(sum(by_account(rows, Measure.FLOW).values()))


# ── Income ─────────────────────────────────────────────────────────────────

def get_monthly_income_totals(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly income totals: {YYYY-MM: float}."""
    rows = slice_rows(master_rows(Measure.FLOW), accounts="income", date_from=date_from, date_to=date_to)
    months = months_in_range(date_from, date_to)
    period_totals = by_period(rows, Measure.FLOW)
    return {m: abs(period_totals.get(m, 0.0)) for m in months}


def get_income_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """Income totals by source: [{account, full_account, amount}] sorted desc."""
    rows = slice_rows(master_rows(Measure.FLOW), accounts="income", depth=depth, date_from=date_from, date_to=date_to)
    results = []
    for account, amount in by_account(rows, Measure.FLOW).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_income_total(date_from: str, date_to: str) -> float:
    rows = slice_rows(master_rows(Measure.FLOW), accounts="income", date_from=date_from, date_to=date_to)
    return abs(sum(by_account(rows, Measure.FLOW).values()))


def get_summary(date_from: str, date_to: str) -> dict:
    """Total income, expenses, net, and savings_rate for a date range."""
    income = get_income_total(date_from, date_to)
    expenses = get_expense_total(date_from, date_to)
    net = income - expenses
    savings_rate = (net / income * 100) if income > 0 else 0.0
    return {"income": income, "expenses": expenses, "net": net, "savings_rate": savings_rate}


# ── Net Worth ──────────────────────────────────────────────────────────────

def get_net_worth_history(date_from: str, date_to: str) -> list[dict]:
    """
    Monthly net worth snapshots: [{month, assets, liabilities, net_worth}].
    STOCK measure (--historical) means each month reflects the true cumulative balance.
    """
    months = months_in_range(date_from, date_to)

    stock = master_rows(Measure.STOCK)
    asset_rows = slice_rows(stock, accounts="assets", date_from=date_from, date_to=date_to)
    liability_rows = slice_rows(stock, accounts="liabilities", date_from=date_from, date_to=date_to)
    asset_totals = by_period(asset_rows, Measure.STOCK)
    liability_totals = by_period(liability_rows, Measure.STOCK)

    result = []
    for m in months:
        assets = asset_totals.get(m, 0.0)
        liabilities = abs(liability_totals.get(m, 0.0))
        result.append({
            "month": m,
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": assets - liabilities,
        })
    return result


def get_net_worth_snapshot(as_of_month: str) -> dict:
    """
    Current net worth breakdown: {liquid, invested, liabilities, net_worth}.
    Balances are as of end of as_of_month (YYYY-MM).
    """
    stock = master_rows(Measure.STOCK)

    def _total(accounts: str) -> float:
        rows = slice_rows(stock, accounts=accounts, date_to=as_of_month)
        return sum(by_account(rows, Measure.STOCK).values())

    total_assets = _total("assets")
    invested = _total("assets:investment")
    liabilities = abs(_total("liabilities"))
    liquid = total_assets - invested

    return {
        "liquid": liquid,
        "invested": invested,
        "liabilities": liabilities,
        "net_worth": total_assets - liabilities,
    }


# ── Transactions ───────────────────────────────────────────────────────────

def get_transactions(date_from: str, date_to: str) -> list[dict]:
    """
    All transactions in date range as a flat list, one row per transaction.
    Sign convention (hledger print default, no --reverse needed):
      negative posting = FROM (money source), positive posting = TO (destination).
    Returns [{date, description, from_account, to_account, amount, kind}] most-recent first.
    kind is 'expense' | 'income' | 'transfer'.

    hledger print doesn't support --layout=tidy, so this keeps its own parser
    (out of scope for the master-pull tidy-CSV pipeline — see PLAN.md Phase 1.5).
    """
    output = run_hledger(
        "print", "--output-format", "csv",
        "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)

    seen: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        idx = row.get("txnidx", "").strip()
        if not idx:
            continue
        if idx not in seen:
            seen[idx] = {
                "date":        row.get("date", "").strip(),
                "description": row.get("description", "").strip(),
                "postings":    [],
            }
            order.append(idx)
        account   = row.get("account", "").strip()
        commodity = row.get("commodity", "").strip()
        try:
            amount_val = float(row.get("amount", "0").replace(",", ""))
        except ValueError:
            amount_val = 0.0
        if account:
            seen[idx]["postings"].append({
                "account":   account,
                "amount_val": amount_val,
                "commodity": commodity,
            })

    result = []
    for idx in reversed(order):
        txn = seen[idx]
        postings = txn["postings"]

        pos = [p for p in postings if p["amount_val"] > 0]
        neg = [p for p in postings if p["amount_val"] < 0]

        if pos:
            amt_val   = pos[0]["amount_val"]
            commodity = pos[0]["commodity"]
        elif neg:
            amt_val   = abs(neg[0]["amount_val"])
            commodity = neg[0]["commodity"]
        else:
            amt_val, commodity = 0.0, ""

        amount_display = f"{amt_val:,.2f} {commodity}".strip() if commodity else f"{amt_val:,.2f}"

        def _kind(acct: str) -> str:
            if acct.startswith("expenses"):
                return "expense"
            if acct.startswith("income"):
                return "income"
            if acct.startswith("assets:investment"):
                return "investment"
            return "account"

        # Split into category (expense/income/investment) vs real account (assets/liabilities)
        category_p = next((p for p in postings if _kind(p["account"]) in ("expense", "income", "investment")), None)
        account_p  = next((p for p in postings if _kind(p["account"]) == "account"), None)

        # Fallback for pure transfers (both sides are assets/liabilities)
        if category_p is None and account_p is not None:
            other = next((p for p in postings if p is not account_p), None)
            category_p = other

        category_acct = category_p["account"] if category_p else ""
        account_acct  = account_p["account"]  if account_p  else ""

        if category_p:
            k = _kind(category_p["account"])
        else:
            k = "transfer"
        kind = k if k != "account" else "transfer"

        result.append({
            "date":             txn["date"],
            "description":      txn["description"],
            "category_account": category_acct,
            "real_account":     account_acct,
            "amount":           amount_display,
            "kind":             kind,
        })

    return result


# ── Accounts ──────────────────────────────────────────────────────────────

def get_account_list() -> dict[str, list[str]]:
    """Depth-2 asset and liability account names: {"assets": [...], "liabilities": [...]}."""
    output = run_hledger("accounts", "--depth", "2", "assets", "liabilities")
    result: dict[str, list[str]] = {"assets": [], "liabilities": []}
    for line in output.splitlines():
        line = line.strip()
        if line.count(":") == 1:
            if line.startswith("assets:"):
                result["assets"].append(line)
            elif line.startswith("liabilities:"):
                result["liabilities"].append(line)
    return result


def get_account_register(account: str, date_from: str, date_to: str) -> list[dict]:
    """Bank-statement view for one account, most-recent first.
    Returns [{date, description, amount_val, amount, balance}].

    hledger register doesn't support --layout=tidy, so this keeps its own
    parser (out of scope for the master-pull tidy-CSV pipeline — see PLAN.md Phase 1.5).
    """
    output = run_hledger(
        "register", account,
        "--output-format", "csv",
        "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)
    result = []
    for row in rows:
        amt_str = row.get("amount", "0").strip()
        bal_str = row.get("total", "0").strip()
        amt_val = _parse_single_amount(amt_str)
        result.append({
            "date":        row.get("date", "").strip(),
            "description": row.get("description", "").strip(),
            "amount_val":  amt_val,
            "amount":      amt_str,
            "balance":     bal_str,
        })
    result.reverse()
    return result


# ── Investments ────────────────────────────────────────────────────────────

def get_investment_breakdown(as_of_month: str) -> list[dict]:
    """Current balance by assets:investment sub-account (depth 3)."""
    rows = slice_rows(master_rows(Measure.STOCK), accounts="assets:investment", depth=3, date_to=as_of_month)
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_monthly_investment_total(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly cumulative total of assets:investment: {YYYY-MM: float}."""
    months = months_in_range(date_from, date_to)
    rows = slice_rows(master_rows(Measure.STOCK), accounts="assets:investment", date_from=date_from, date_to=date_to)
    period_totals = by_period(rows, Measure.STOCK)
    return {m: period_totals.get(m, 0.0) for m in months}


def get_asset_breakdown(as_of_month: str) -> list[dict]:
    """Depth-2 asset breakdown as of end of given month."""
    rows = slice_rows(master_rows(Measure.STOCK), accounts="assets", depth=2, date_to=as_of_month)
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_liability_breakdown(as_of_month: str) -> list[dict]:
    """Credit card balance breakdown as of end of given month."""
    rows = slice_rows(master_rows(Measure.STOCK), accounts="liabilities", depth=2, date_to=as_of_month)
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


# ── Sankey ─────────────────────────────────────────────────────────────────

def get_sankey_data(date_from: str, date_to: str) -> dict:
    """
    Money flow for a date range: income sources -> "Income" hub -> expense
    categories / investments / savings. Built on the same FLOW queries as
    get_income_breakdown/get_expense_breakdown, so it agrees with those
    numbers by construction.
    Returns {"nodes": [{"name": str}], "links": [{"source", "target", "value"}]}.
    """
    flow = master_rows(Measure.FLOW)
    income_rows = slice_rows(flow, accounts="income", depth=2, date_from=date_from, date_to=date_to)
    expense_rows = slice_rows(flow, accounts="expenses", depth=2, date_from=date_from, date_to=date_to)
    invest_rows = slice_rows(flow, accounts="assets:investment", date_from=date_from, date_to=date_to)

    income_by_account = by_account(income_rows, Measure.FLOW)
    expense_by_account = by_account(expense_rows, Measure.FLOW)
    # Net new money moved into investment accounts this period (a FLOW, not
    # the STOCK balance) — positive means contributions outweighed withdrawals.
    invested = max(sum(by_account(invest_rows, Measure.FLOW).values()), 0.0)

    total_income = sum(abs(v) for v in income_by_account.values())
    total_expenses = sum(abs(v) for v in expense_by_account.values())
    savings = max(total_income - total_expenses - invested, 0.0)

    nodes: list[dict] = [{"name": "Income"}]
    links: list[dict] = []
    used_names = {"Income"}

    def _unique_name(name: str) -> str:
        # ECharts sankey identifies nodes by name, and an income category and
        # an expense category can legitimately share a leaf name (e.g. both
        # "transfer") since they come from separate account trees — that
        # silently crashes ECharts' internal graph builder (a node lookup by
        # name resolves ambiguously). Disambiguate any collision so every
        # node name passed to the chart is unique.
        if name not in used_names:
            used_names.add(name)
            return name
        i = 2
        candidate = f"{name} ({i})"
        while candidate in used_names:
            i += 1
            candidate = f"{name} ({i})"
        used_names.add(candidate)
        return candidate

    for account, amount in income_by_account.items():
        amount = abs(amount)
        if amount <= 0:
            continue
        name = _unique_name(_short_name(account))
        nodes.append({"name": name})
        links.append({"source": name, "target": "Income", "value": amount})

    for account, amount in expense_by_account.items():
        amount = abs(amount)
        if amount <= 0:
            continue
        name = _unique_name(_short_name(account))
        nodes.append({"name": name})
        links.append({"source": "Income", "target": name, "value": amount})

    if invested > 0:
        name = _unique_name("Investments")
        nodes.append({"name": name})
        links.append({"source": "Income", "target": name, "value": invested})

    if savings > 0:
        name = _unique_name("Savings")
        nodes.append({"name": name})
        links.append({"source": "Income", "target": name, "value": savings})

    return {"nodes": nodes, "links": links}


# ── Budget ─────────────────────────────────────────────────────────────────

def get_budget_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """
    Percent of budget consumed per expense category for a date range, from
    the periodic (~) transactions in the journal.

    Uses a dedicated non-tidy parser: hledger's --budget silently ignores
    --layout=tidy (verified against hledger 1.50.2 — see PLAN.md Phase 1.1),
    always emitting the wide actual/budget paired-column CSV instead, so
    this bypasses the master-pull tidy-CSV pipeline entirely rather than risk
    misparsing that shape as tidy rows.
    Returns [{account, full_account, actual, budget, pct}] sorted by pct
    descending (categories over budget first); pct is None with no budget goal.
    """
    output = run_hledger(
        "balance", "expenses", "--budget",
        "--output-format", "csv", "--depth", str(depth),
        "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)
    results = []
    for row in rows:
        account = row.get("Account", "").strip()
        if not account or account.lower().startswith("total"):
            continue
        value_cols = [k for k in row.keys() if k != "Account"]
        if len(value_cols) < 2:
            continue
        actual = abs(_parse_single_amount(row.get(value_cols[0], "0")))
        budget = abs(_parse_single_amount(row.get(value_cols[1], "0")))
        pct = (actual / budget * 100) if budget > 0 else None
        results.append({
            "account": _short_name(account),
            "full_account": account,
            "actual": actual,
            "budget": budget,
            "pct": pct,
        })
    results.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))
    return results
