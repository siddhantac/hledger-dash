#!/usr/bin/env python3
"""
Generates testdata/synthetic.journal — a deterministic multi-year hledger
journal used by the V0/V1 tests described in PLAN.md.

Covers: multiple years, multiple commodities (USD + BTC), assets,
liabilities, investments, income, several expense categories, a periodic
~ budget transaction, one amount >= 1,000,000, and an explicit December
transaction in every year.

Re-run with `python testdata/generate_journal.py` after editing this file.
"""
from pathlib import Path

OUT = Path(__file__).parent / "synthetic.journal"

START_YEAR = 2024
END_YEAR = 2026
END_MONTH = 7  # journal covers through 2026-07 (mirrors "today" in CLAUDE.md context)

lines: list[str] = []


def txn(date: str, desc: str, postings: list[str]) -> None:
    lines.append(f"{date} * {desc}")
    for p in postings:
        lines.append(f"    {p}")
    lines.append("")


def months():
    for y in range(START_YEAR, END_YEAR + 1):
        last_m = END_MONTH if y == END_YEAR else 12
        for m in range(1, last_m + 1):
            yield y, m


# ── Commodity directives ─────────────────────────────────────────────────
lines.append("commodity USD")
lines.append("    format 1,000.00 USD")
lines.append("")
lines.append("commodity BTC")
lines.append("    format 1,000.00000000 BTC")
lines.append("")

# ── Budget goals (periodic transaction) ──────────────────────────────────
lines.append("~ monthly from 2024-01-01")
lines.append("    expenses:rent               2000.00 USD")
lines.append("    expenses:food                600.00 USD")
lines.append("    expenses:transport           150.00 USD")
lines.append("    expenses:utilities           120.00 USD")
lines.append("    expenses:entertainment        80.00 USD")
lines.append("    assets:checking")
lines.append("")

# ── Opening balances ──────────────────────────────────────────────────────
txn("2024-01-01", "Opening Balances", [
    "assets:checking              10000.00 USD",
    "assets:savings                 5000.00 USD",
    "assets:investment:brokerage    2000.00 USD",
    "liabilities:creditcard         -500.00 USD",
    "equity:opening balances",
])

food_cycle = [420.00, 480.00, 510.00, 550.00, 460.00, 600.00]
transport_cycle = [140.00, 150.00, 160.00, 145.00]
entertainment_cycle = [60.00, 90.00, 80.00, 110.00, 70.00]

i = 0
for y, m in months():
    ym = f"{y}-{m:02d}"
    idx = i
    i += 1

    # Income: salary always, freelance every 3rd month
    txn(f"{ym}-01", "Employer Payroll", [
        "assets:checking              5000.00 USD",
        "income:salary                -5000.00 USD",
    ])
    if idx % 3 == 0:
        txn(f"{ym}-05", "Freelance Client Invoice", [
            "assets:checking               800.00 USD",
            "income:freelance             -800.00 USD",
        ])

    # Expenses
    txn(f"{ym}-03", "Rent Payment", [
        "expenses:rent                2000.00 USD",
        "assets:checking              -2000.00 USD",
    ])
    txn(f"{ym}-07", "Groceries", [
        f"expenses:food                 {food_cycle[idx % len(food_cycle)]:.2f} USD",
        f"liabilities:creditcard        -{food_cycle[idx % len(food_cycle)]:.2f} USD",
    ])
    txn(f"{ym}-10", "Transit Pass", [
        f"expenses:transport            {transport_cycle[idx % len(transport_cycle)]:.2f} USD",
        f"liabilities:creditcard        -{transport_cycle[idx % len(transport_cycle)]:.2f} USD",
    ])
    txn(f"{ym}-12", "Electricity & Water", [
        "expenses:utilities            120.00 USD",
        "assets:checking               -120.00 USD",
    ])
    txn(f"{ym}-18", "Dining & Movies", [
        f"expenses:entertainment        {entertainment_cycle[idx % len(entertainment_cycle)]:.2f} USD",
        f"liabilities:creditcard        -{entertainment_cycle[idx % len(entertainment_cycle)]:.2f} USD",
    ])

    # Credit card payoff
    txn(f"{ym}-20", "Credit Card Payment", [
        "liabilities:creditcard        700.00 USD",
        "assets:checking               -700.00 USD",
    ])

    # Investment contribution, alternating commodity to exercise multi-commodity parsing
    if idx % 2 == 0:
        txn(f"{ym}-25", "Brokerage Contribution", [
            "assets:investment:brokerage   500.00 USD",
            "assets:checking              -500.00 USD",
        ])
    else:
        btc_amt = 0.01000000
        txn(f"{ym}-25", "Crypto Purchase", [
            f"assets:investment:crypto      {btc_amt:.8f} BTC @ 50000.00 USD",
            "assets:checking              -500.00 USD",
        ])

    # Explicit December transaction each year — regression cover for the
    # Go project's `t.Month()+1` -> "2025-13" bug.
    if m == 12:
        txn(f"{y}-12-24", "Holiday Bonus", [
            "assets:checking               1000.00 USD",
            "income:salary                -1000.00 USD",
        ])

# ── One amount >= 1,000,000 — regression cover for the Go project's
#    comma-stripping bug (strings.Replace(num, ",", "", 1)). ─────────────
txn("2025-06-15", "Stock Sale Windfall", [
    "assets:checking              1200000.00 USD",
    "income:investment_gains     -1200000.00 USD",
])
# Immediately move most of it into savings so net worth / asset breakdowns
# also see a >= 1,000,000 balance, not just a flow.
txn("2025-06-16", "Move Windfall to Savings", [
    "assets:savings                1150000.00 USD",
    "assets:checking              -1150000.00 USD",
])

OUT.write_text("\n".join(lines) + "\n")
print(f"wrote {OUT} ({len(lines)} lines)")
