"""
Tidy-CSV query layer over the hledger CLI.

Two master pulls (one FLOW, one STOCK — see `hledger.py`'s `master_rows`)
fetch the entire journal's `--layout=tidy --output-format=csv --cost
--value=then` history once per journal-mtime-change. Every `get_*` function in
`hledger.py` then calls `slice_rows()` to filter/depth-truncate/date-window
that in-memory dataset into the same six-column tidy row shape
(`account,period,start_date,end_date,commodity,value`) a narrow per-call
hledger query used to produce directly, before handing off to the shaping
helpers below. This replaces what used to be up to 17 distinct per-page
hledger subprocess invocations with exactly 2, shared across every page and
every date range (see PERFORMANCE.md).

FLOW vs STOCK is structural, not a per-call convention: the STOCK master pull
always carries `--historical`, so a stock measure can never accidentally be
summed across months by a caller that forgot the flag.
"""
import re
from enum import Enum


class Measure(Enum):
    FLOW = "flow"    # summable over a period: income, expenses
    STOCK = "stock"  # point-in-time: assets, investments, net worth


def by_account(rows: list[dict], measure: Measure) -> dict[str, float]:
    """
    Collapse tidy rows into {account: float}.
    FLOW sums every period's value; STOCK keeps only the last period's value
    (the current/point-in-time balance), never the sum across periods.
    """
    if measure is Measure.FLOW:
        result: dict[str, float] = {}
        for row in rows:
            result[row["account"]] = result.get(row["account"], 0.0) + float(row["value"])
        return result

    latest_end: dict[str, str] = {}
    latest_val: dict[str, float] = {}
    for row in rows:
        account, end_date, value = row["account"], row["end_date"], float(row["value"])
        if account not in latest_end or end_date > latest_end[account]:
            latest_end[account] = end_date
            latest_val[account] = value
    return latest_val


def by_period(rows: list[dict], measure: Measure) -> dict[str, float]:
    """
    Collapse tidy rows into {period: float}, summed across accounts.
    FLOW and STOCK are handled identically here: the flow/stock distinction
    is already baked into each row's value by whether the master pull used
    --historical, so both cases just sum same-period rows.
    """
    result: dict[str, float] = {}
    for row in rows:
        result[row["period"]] = result.get(row["period"], 0.0) + float(row["value"])
    return result


def pivot(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Collapse tidy rows into {account: {period: float}}."""
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        result.setdefault(row["account"], {})[row["period"]] = float(row["value"])
    return result


def _truncate_depth(account: str, depth: int) -> str:
    return ":".join(account.split(":")[:depth])


def _account_matches(pattern: str, account: str) -> bool:
    # hledger's own account-pattern matching is a case-insensitive, unanchored
    # regex search against the full account name (verified against hledger
    # 1.50.2: "ASSETS" matches "assets:checking"; "invest" mid-string matches
    # "assets:investment:brokerage") — re.search replicates this exactly.
    return re.search(pattern, account, re.IGNORECASE) is not None


def slice_rows(
    rows: list[dict],
    accounts: str,
    depth: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Filter/truncate/date-window a master pull's rows into the same tidy shape
    a narrow per-call hledger query would have produced, so
    by_account/by_period/pivot can consume them unchanged.

    date_from/date_to compare period strings directly ("2024-03" >= "2024-01")
    since master rows are always --monthly, so period is always a plain
    YYYY-MM string with no day-level range math to get wrong.
    """
    filtered = [
        row for row in rows
        if _account_matches(accounts, row["account"])
        and (date_from is None or row["period"] >= date_from)
        and (date_to is None or row["period"] <= date_to)
    ]

    if depth is not None:
        grouped: dict[tuple[str, str], dict] = {}
        for row in filtered:
            key = (_truncate_depth(row["account"], depth), row["period"])
            if key in grouped:
                grouped[key]["value"] = str(float(grouped[key]["value"]) + float(row["value"]))
            else:
                grouped[key] = {**row, "account": key[0]}
        filtered = list(grouped.values())

    # The master pull spans the whole journal, so hledger emits an explicit
    # "0" row for any account with nonzero activity somewhere in the journal
    # but not within this window, to keep its own multi-period table
    # rectangular. A real narrower hledger call scoped to just this window
    # would never have produced that account at all. Drop accounts with zero
    # activity across the *entire selected window* to match — but keep an
    # account that has even one nonzero row in-window (e.g. a balance that
    # was fully closed out mid-window still needs its trailing zero row, so
    # by_account's STOCK "last period" pick reflects the true current zero).
    by_acct: dict[str, list[dict]] = {}
    for row in filtered:
        by_acct.setdefault(row["account"], []).append(row)
    return [
        row
        for acct_rows in by_acct.values()
        if any(float(r["value"]) != 0 for r in acct_rows)
        for row in acct_rows
    ]
