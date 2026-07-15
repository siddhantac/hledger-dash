"""
Tidy-CSV query layer over the hledger CLI.

Every query emits `--layout=tidy --output-format=csv --cost --value=then`, so
Python always parses the same six columns
(`account,period,start_date,end_date,commodity,value`) and always receives a
single already-converted commodity — no hand-rolled multi-commodity parsing.

FLOW vs STOCK is structural, not a per-call convention: STOCK queries get
`--historical` appended automatically, so a stock measure can never
accidentally be summed across months by a caller that forgot the flag.
"""
from dataclasses import dataclass
from enum import Enum


class Measure(Enum):
    FLOW = "flow"    # summable over a period: income, expenses
    STOCK = "stock"  # point-in-time: assets, investments, net worth


def _next_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


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

    def argv(self) -> list[str]:
        if self.budget:
            # Verified against hledger 1.50.2 (PLAN.md Phase 1.1): --budget
            # silently ignores --layout=tidy and always emits the wide
            # actual/budget paired-column CSV instead. Budget queries use a
            # dedicated non-tidy parser (Phase 4.2), not this class.
            raise NotImplementedError(
                "hledger --budget does not support --layout=tidy; "
                "use the dedicated budget parser instead of Query"
            )

        args = [
            "balance", self.accounts,
            "--layout=tidy", "--output-format=csv",
            "--cost", "--value=then",
        ]
        if self.measure is Measure.STOCK:
            args.append("--historical")
        if self.monthly:
            args.append("--monthly")
        if self.depth is not None:
            args += ["--depth", str(self.depth)]
        if self.drop is not None:
            args += ["--drop", str(self.drop)]
        if self.invert:
            args.append("--invert")

        period = self._period()
        if period is not None:
            args += ["--period", period]
        return args

    def _period(self) -> str | None:
        if self.date_from and self.date_to:
            return f"{self.date_from}..{_next_month(self.date_to)}"
        if self.date_to:
            return f"..{_next_month(self.date_to)}"
        if self.date_from:
            return f"{self.date_from}.."
        return None


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
    is already baked into each row's value by whether --historical was sent
    to hledger (see Query.argv), so both cases just sum same-period rows.
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
