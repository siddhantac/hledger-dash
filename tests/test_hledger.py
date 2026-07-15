"""
Integration tests for app/services/hledger.py against testdata/synthetic.journal.

Expected values were hand-verified with plain `hledger balance ... -N` calls
independent of app.services.query (see PLAN.md V1) — not derived from the
code under test.
"""
import pytest

from app.services import hledger as hl


def test_expense_total_2024():
    assert hl.get_expense_total("2024-01", "2024-12") == pytest.approx(34235.00)


def test_income_total_2024():
    assert hl.get_income_total("2024-01", "2024-12") == pytest.approx(64200.00)


def test_expense_breakdown_2024_amounts():
    breakdown = {r["full_account"]: r["amount"] for r in hl.get_expense_breakdown("2024-01", "2024-12")}
    assert breakdown == {
        "expenses:entertainment": pytest.approx(970.00),
        "expenses:food": pytest.approx(6040.00),
        "expenses:rent": pytest.approx(24000.00),
        "expenses:transport": pytest.approx(1785.00),
        "expenses:utilities": pytest.approx(1440.00),
    }
    # sorted descending by amount
    amounts = [r["amount"] for r in hl.get_expense_breakdown("2024-01", "2024-12")]
    assert amounts == sorted(amounts, reverse=True)


def test_net_worth_snapshot_is_point_in_time_not_summed():
    snap = hl.get_net_worth_snapshot("2026-07")
    # assets: checking 122,880 + brokerage 10,000 + crypto 7,500 (BTC valued at cost-then) + savings 1,155,000
    assert snap["liabilities"] == pytest.approx(1455.00)
    assert snap["net_worth"] == pytest.approx(1295380.00 - 1455.00)
    # STOCK regression: a monthly sum over 31 months would be enormous (>> net worth).
    # If by_account ever regresses to summing STOCK periods, this catches it.
    assert snap["net_worth"] < 5_000_000


def test_net_worth_history_stock_not_summed_across_months():
    history = hl.get_net_worth_history("2024-01", "2024-06")
    by_month = {r["month"]: r for r in history}
    # Hand-verified: assets as of end of each month (checking+savings+brokerage/crypto)
    assert by_month["2024-01"]["assets"] == pytest.approx(19980.00)
    # Net worth must be monotonically non-decreasing here (no expense month wipes
    # out savings) — a red flag that stock values are being summed instead of
    # taken as point-in-time would show wildly increasing/inconsistent jumps.
    assets_seq = [by_month[m]["assets"] for m in sorted(by_month)]
    assert assets_seq == sorted(assets_seq)


def test_investment_breakdown_as_of_2026_07():
    breakdown = {r["full_account"]: r["amount"] for r in hl.get_investment_breakdown("2026-07")}
    assert breakdown == {
        "assets:investment:brokerage": pytest.approx(10000.00),
        "assets:investment:crypto": pytest.approx(7500.00),
    }


def test_monthly_investment_total_is_historical_balance_not_flow():
    totals = hl.get_monthly_investment_total("2024-01", "2024-02")
    # Jan: only the opening 2000 + first 500 contribution = 2500, not the
    # 500/mo *contribution flow* — confirms STOCK semantics.
    assert totals["2024-01"] == pytest.approx(2500.00)


def test_million_dollar_amount_is_not_truncated_to_zero():
    # Regression cover for the Go project's comma-parsing bug
    # (strings.Replace(num, ",", "", 1) only strips the first comma).
    breakdown = hl.get_income_breakdown("2025-06", "2025-06")
    gains = next(r for r in breakdown if r["full_account"] == "income:investment_gains")
    assert gains["amount"] == pytest.approx(1200000.00)


def test_december_transaction_is_included():
    # Regression cover for the Go project's `t.Month()+1` -> "2025-13" bug.
    totals = hl.get_monthly_income_totals("2024-12", "2024-12")
    assert totals["2024-12"] > 5000.00  # salary + December holiday bonus


def test_available_years_spans_synthetic_journal():
    years = hl.available_years()
    assert years == [2024, 2025, 2026]


def test_months_in_range():
    assert hl.months_in_range("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
