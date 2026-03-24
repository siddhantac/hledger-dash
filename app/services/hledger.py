import csv
import io
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def _journal_file() -> str:
    path = os.environ.get("HLEDGER_FILE", "")
    if not path:
        raise RuntimeError("HLEDGER_FILE environment variable is not set")
    return path


def run_hledger(*args: str) -> str:
    """Run an hledger command and return stdout as a string."""
    cmd = ["hledger", "-f", _journal_file(), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Command failed: %s\nstderr: %s", " ".join(cmd), result.stderr.strip())
        raise RuntimeError(f"hledger error: {result.stderr.strip()}")
    return result.stdout


def _next_month(ym: str) -> str:
    """Return the YYYY-MM of the month after the given YYYY-MM string."""
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def _period_arg(date_from: str, date_to: str) -> str:
    """
    Build a hledger period string from YYYY-MM range strings.
    hledger ranges are exclusive on the end, so we add one month to date_to.
    """
    if date_from == date_to:
        return date_from
    return f"{date_from}..{_next_month(date_to)}"


def _parse_csv(output: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(output))
    return [row for row in reader]


def _amount_to_float(amount_str: str) -> float:
    """Convert hledger amount string like '1,234.56 GBP' to a float."""
    cleaned = amount_str.replace(",", "").strip()
    parts = cleaned.split()
    for part in parts:
        try:
            return float(part)
        except ValueError:
            continue
    return 0.0


def months_in_range(date_from: str, date_to: str) -> list[str]:
    """Return list of YYYY-MM strings from date_from to date_to inclusive."""
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


def get_monthly_totals(date_from: str, date_to: str, account_query: str) -> dict[str, float]:
    """
    Return {YYYY-MM: amount} totals for the given account query and date range.
    Aggregates across all sub-accounts.
    """
    output = run_hledger(
        "balance", account_query,
        "--monthly", "--output-format", "csv",
        "--no-total", "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)
    totals: dict[str, float] = {}
    for row in rows:
        for key, val in row.items():
            if key == "account":
                continue
            # Column headers are YYYY-MM
            if len(key) == 7 and key[4] == "-":
                totals[key] = totals.get(key, 0.0) + abs(_amount_to_float(val))
    return totals


def get_expense_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """
    Return expense totals by category for the given date range.
    Returns list of {account, full_account, amount} sorted by amount desc.
    """
    output = run_hledger(
        "balance", "expenses",
        "--output-format", "csv",
        "--no-total", "--depth", str(depth),
        "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)
    results = []
    for row in rows:
        account = row.get("account", "").strip()
        amount = abs(_amount_to_float(row.get("balance", "0")))
        if account and amount > 0:
            short = account.split(":")[-1] if ":" in account else account
            results.append({"account": short, "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_income_breakdown(date_from: str, date_to: str, depth: int = 2) -> list[dict]:
    """Return income totals by source for the given date range."""
    output = run_hledger(
        "balance", "income",
        "--output-format", "csv",
        "--no-total", "--depth", str(depth),
        "--period", _period_arg(date_from, date_to),
    )
    rows = _parse_csv(output)
    results = []
    for row in rows:
        account = row.get("account", "").strip()
        amount = abs(_amount_to_float(row.get("balance", "0")))
        if account and amount > 0:
            short = account.split(":")[-1] if ":" in account else account
            results.append({"account": short, "full_account": account, "amount": amount})
    results.sort(key=lambda x: x["amount"], reverse=True)
    return results


def get_summary(date_from: str, date_to: str) -> dict:
    """Return total income, expenses, and net for a date range."""
    period = _period_arg(date_from, date_to)

    def _total(account_query: str) -> float:
        output = run_hledger(
            "balance", account_query,
            "--output-format", "csv",
            "--period", period,
        )
        rows = _parse_csv(output)
        for row in reversed(rows):
            amt = _amount_to_float(row.get("balance", "0"))
            if amt != 0:
                return abs(amt)
        return 0.0

    income = _total("income")
    expenses = _total("expenses")
    return {"income": income, "expenses": expenses, "net": income - expenses}


def _parse_report_csv(output: str) -> dict:
    """
    Parse hledger report CSV into structured data for table rendering.
    Returns {title, columns, rows} where each row has:
      account, amounts[], is_section, is_total, depth
    """
    lines = list(csv.reader(io.StringIO(output)))
    if len(lines) < 2:
        return {"title": "", "columns": [], "rows": []}

    title = lines[0][0] if lines[0] else ""
    columns = lines[1] if len(lines) > 1 else []

    rows = []
    for line in lines[2:]:
        if not line:
            continue
        account = line[0]
        amounts = line[1:]
        is_section = all(a == "" for a in amounts)
        is_total = account.lower() == "total"
        depth = account.count(":") if not is_section and not is_total else 0
        rows.append({
            "account": account,
            "amounts": amounts,
            "is_section": is_section,
            "is_total": is_total,
            "depth": depth,
        })

    return {"title": title, "columns": columns, "rows": rows}


def get_income_statement(date_from: str, date_to: str, period_type: str = "monthly") -> dict:
    """Return parsed incomestatement as table data. period_type: monthly, quarterly, yearly."""
    output = run_hledger(
        "incomestatement",
        "--period", _period_arg(date_from, date_to),
        f"--{period_type}",
        "--output-format", "csv",
    )
    return _parse_report_csv(output)


def get_balance_sheet(date_from: str, date_to: str, period_type: str = "monthly") -> dict:
    """Return parsed balancesheet as table data. period_type: monthly, quarterly, yearly."""
    output = run_hledger(
        "balancesheet",
        "--period", _period_arg(date_from, date_to),
        f"--{period_type}",
        "--output-format", "csv",
    )
    return _parse_report_csv(output)
