import csv
import io
import logging
import os
import subprocess
from datetime import date
from functools import lru_cache

from app.services.query import Measure, Query, by_account, by_period, pivot

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


def _run_query(q: Query) -> list[dict]:
    return _parse_csv(run_hledger(*q.argv()))


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
    rows = _run_query(Query(
        accounts="expenses", measure=Measure.FLOW,
        date_from=date_from, date_to=date_to, depth=depth, monthly=True,
    ))
    by_full_account = pivot(rows)
    result: dict[str, dict[str, float]] = {}
    for account, monthly in by_full_account.items():
        monthly = {m: abs(v) for m, v in monthly.items()}
        if any(v > 0 for v in monthly.values()):
            result[_short_name(account)] = monthly
    return result


def get_monthly_expense_totals(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly expense totals: {YYYY-MM: float}."""
    rows = _run_query(Query(
        accounts="expenses", measure=Measure.FLOW,
        date_from=date_from, date_to=date_to, monthly=True,
    ))
    months = months_in_range(date_from, date_to)
    period_totals = by_period(rows, Measure.FLOW)
    return {m: abs(period_totals.get(m, 0.0)) for m in months}


def get_expense_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """Expense totals by category: [{account, full_account, amount}] sorted desc."""
    rows = _run_query(Query(
        accounts="expenses", measure=Measure.FLOW,
        date_from=date_from, date_to=date_to, depth=depth,
    ))
    results = []
    for account, amount in by_account(rows, Measure.FLOW).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_expense_total(date_from: str, date_to: str) -> float:
    rows = _run_query(Query(accounts="expenses", measure=Measure.FLOW, date_from=date_from, date_to=date_to))
    return abs(sum(by_account(rows, Measure.FLOW).values()))


# ── Income ─────────────────────────────────────────────────────────────────

def get_monthly_income_totals(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly income totals: {YYYY-MM: float}."""
    rows = _run_query(Query(
        accounts="income", measure=Measure.FLOW,
        date_from=date_from, date_to=date_to, monthly=True,
    ))
    months = months_in_range(date_from, date_to)
    period_totals = by_period(rows, Measure.FLOW)
    return {m: abs(period_totals.get(m, 0.0)) for m in months}


def get_income_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """Income totals by source: [{account, full_account, amount}] sorted desc."""
    rows = _run_query(Query(
        accounts="income", measure=Measure.FLOW,
        date_from=date_from, date_to=date_to, depth=depth,
    ))
    results = []
    for account, amount in by_account(rows, Measure.FLOW).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_income_total(date_from: str, date_to: str) -> float:
    rows = _run_query(Query(accounts="income", measure=Measure.FLOW, date_from=date_from, date_to=date_to))
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

    asset_rows = _run_query(Query(
        accounts="assets", measure=Measure.STOCK,
        date_from=date_from, date_to=date_to, monthly=True,
    ))
    liability_rows = _run_query(Query(
        accounts="liabilities", measure=Measure.STOCK,
        date_from=date_from, date_to=date_to, monthly=True,
    ))
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
    def _total(accounts: str) -> float:
        rows = _run_query(Query(accounts=accounts, measure=Measure.STOCK, date_to=as_of_month))
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
    (out of scope for the Query rewrite — see PLAN.md Phase 1.5).
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
    parser (out of scope for the Query rewrite — see PLAN.md Phase 1.5).
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
    rows = _run_query(Query(
        accounts="assets:investment", measure=Measure.STOCK,
        date_to=as_of_month, depth=3,
    ))
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_monthly_investment_total(date_from: str, date_to: str) -> dict[str, float]:
    """Monthly cumulative total of assets:investment: {YYYY-MM: float}."""
    months = months_in_range(date_from, date_to)
    rows = _run_query(Query(
        accounts="assets:investment", measure=Measure.STOCK,
        date_from=date_from, date_to=date_to, monthly=True,
    ))
    period_totals = by_period(rows, Measure.STOCK)
    return {m: period_totals.get(m, 0.0) for m in months}


def get_asset_breakdown(as_of_month: str) -> list[dict]:
    """Depth-2 asset breakdown as of end of given month."""
    rows = _run_query(Query(
        accounts="assets", measure=Measure.STOCK,
        date_to=as_of_month, depth=2,
    ))
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_liability_breakdown(as_of_month: str) -> list[dict]:
    """Credit card balance breakdown as of end of given month."""
    rows = _run_query(Query(
        accounts="liabilities", measure=Measure.STOCK,
        date_to=as_of_month, depth=2,
    ))
    results = []
    for account, amount in by_account(rows, Measure.STOCK).items():
        amount = abs(amount)
        if account and amount > 0:
            results.append({"account": _short_name(account), "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results
