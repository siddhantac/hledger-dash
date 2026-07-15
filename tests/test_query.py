"""Unit tests for the tidy-CSV shaping helpers, no hledger process involved."""
import pytest

from app.services.query import Measure, Query, by_account, by_period, pivot

FLOW_ROWS = [
    {"account": "expenses:rent", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "2000.00"},
    {"account": "expenses:rent", "period": "2024-02", "start_date": "2024-02-01", "end_date": "2024-02-29", "commodity": "USD", "value": "2000.00"},
    {"account": "expenses:food", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "400.00"},
    {"account": "expenses:food", "period": "2024-02", "start_date": "2024-02-01", "end_date": "2024-02-29", "commodity": "USD", "value": "450.00"},
]

STOCK_ROWS = [
    {"account": "assets:checking", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "1000.00"},
    {"account": "assets:checking", "period": "2024-02", "start_date": "2024-02-01", "end_date": "2024-02-29", "commodity": "USD", "value": "1500.00"},
    {"account": "assets:savings", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "5000.00"},
    {"account": "assets:savings", "period": "2024-02", "start_date": "2024-02-01", "end_date": "2024-02-29", "commodity": "USD", "value": "5000.00"},
]


def test_by_account_flow_sums_across_periods():
    assert by_account(FLOW_ROWS, Measure.FLOW) == {
        "expenses:rent": 4000.00,
        "expenses:food": 850.00,
    }


def test_by_account_stock_keeps_last_period_only():
    # Must be the LAST period's value (Feb), never the sum (2500/6500).
    assert by_account(STOCK_ROWS, Measure.STOCK) == {
        "assets:checking": 1500.00,
        "assets:savings": 5000.00,
    }


def test_by_period_sums_across_accounts():
    assert by_period(FLOW_ROWS, Measure.FLOW) == {
        "2024-01": 2400.00,
        "2024-02": 2450.00,
    }
    assert by_period(STOCK_ROWS, Measure.STOCK) == {
        "2024-01": 6000.00,
        "2024-02": 6500.00,
    }


def test_pivot_is_account_to_period_map():
    assert pivot(FLOW_ROWS) == {
        "expenses:rent": {"2024-01": 2000.00, "2024-02": 2000.00},
        "expenses:food": {"2024-01": 400.00, "2024-02": 450.00},
    }


def test_query_argv_flow_has_no_historical():
    argv = Query(accounts="expenses", measure=Measure.FLOW, date_from="2024-01", date_to="2024-02").argv()
    assert "--historical" not in argv
    assert "--layout=tidy" in argv
    assert "--cost" in argv
    assert "--value=then" in argv
    assert "--period" in argv
    assert argv[argv.index("--period") + 1] == "2024-01..2024-03"


def test_query_argv_stock_has_historical():
    argv = Query(accounts="assets", measure=Measure.STOCK, date_to="2024-02").argv()
    assert "--historical" in argv
    assert argv[argv.index("--period") + 1] == "..2024-03"


def test_query_argv_budget_raises_not_implemented():
    # Verified against hledger 1.50.2: --budget ignores --layout=tidy, so
    # budget queries must not go through Query (PLAN.md Phase 1.1/4.2).
    with pytest.raises(NotImplementedError):
        Query(accounts="expenses", measure=Measure.FLOW, budget=True).argv()
