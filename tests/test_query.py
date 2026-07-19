"""Unit tests for the tidy-CSV shaping helpers, no hledger process involved."""
from app.services.query import Measure, _account_matches, _truncate_depth, by_account, by_period, pivot, slice_rows

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


# ── slice_rows: turns master-pull rows into the tidy shape by_account/by_period/pivot expect ──

def test_truncate_depth():
    assert _truncate_depth("assets:investment:brokerage", 1) == "assets"
    assert _truncate_depth("assets:investment:brokerage", 2) == "assets:investment"
    assert _truncate_depth("assets:investment:brokerage", 3) == "assets:investment:brokerage"
    assert _truncate_depth("assets:investment:brokerage", 4) == "assets:investment:brokerage"


def test_account_matches_is_case_insensitive_unanchored_search():
    # Verified against real hledger 1.50.2: account-pattern matching is a
    # case-insensitive, unanchored regex search against the full account name.
    assert _account_matches("assets", "assets:checking")
    assert _account_matches("ASSETS", "assets:checking")
    assert _account_matches("invest", "assets:investment:brokerage")
    assert not _account_matches("liabilities", "assets:checking")


def test_slice_rows_filters_by_account_pattern():
    rows = FLOW_ROWS + STOCK_ROWS
    assert slice_rows(rows, accounts="expenses") == FLOW_ROWS
    assert slice_rows(rows, accounts="assets") == STOCK_ROWS


def test_slice_rows_filters_by_date_window():
    result = slice_rows(FLOW_ROWS, accounts="expenses", date_from="2024-02", date_to="2024-02")
    assert {r["account"] for r in result} == {"expenses:rent", "expenses:food"}
    assert all(r["period"] == "2024-02" for r in result)


def test_slice_rows_depth_truncation_sums_descendants():
    rows = [
        {"account": "assets:investment:brokerage", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "3000.00"},
        {"account": "assets:investment:crypto", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "500.00"},
    ]
    result = slice_rows(rows, accounts="assets:investment", depth=2)
    assert result == [
        {"account": "assets:investment", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "3500.0"},
    ]


def test_slice_rows_drops_accounts_with_zero_activity_across_the_whole_window():
    # hledger's own multi-period reports emit an explicit "0" row for any
    # account with nonzero activity somewhere in the journal but not within a
    # given sub-window, to keep the table rectangular — a real narrower
    # hledger call scoped to just that window would never produce the
    # account at all. slice_rows must replicate that suppression.
    rows = [
        {"account": "income:investment_gains", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "0"},
        {"account": "income:investment_gains", "period": "2025-06", "start_date": "2025-06-01", "end_date": "2025-06-30", "commodity": "USD", "value": "-1200000.00"},
    ]
    # Window excludes the only nonzero month: account must be dropped entirely.
    assert slice_rows(rows, accounts="income", date_from="2024-01", date_to="2024-12") == []
    # Window includes it: both rows (including the zero one) must survive.
    assert slice_rows(rows, accounts="income", date_from="2024-01", date_to="2025-12") == rows


def test_slice_rows_keeps_trailing_zero_row_when_account_closes_out_mid_window():
    # An account that was nonzero earlier in the window and genuinely hits
    # zero later (e.g. fully paid off) must keep its trailing zero row, so
    # by_account's STOCK "last period" pick reflects the true current zero
    # rather than a stale earlier nonzero balance.
    rows = [
        {"account": "liabilities:creditcard", "period": "2024-01", "start_date": "2024-01-01", "end_date": "2024-01-31", "commodity": "USD", "value": "-200.00"},
        {"account": "liabilities:creditcard", "period": "2024-02", "start_date": "2024-02-01", "end_date": "2024-02-29", "commodity": "USD", "value": "0"},
    ]
    result = slice_rows(rows, accounts="liabilities", date_from="2024-01", date_to="2024-02")
    assert by_account(result, Measure.STOCK) == {"liabilities:creditcard": 0.0}
