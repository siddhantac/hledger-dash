"""
Caching has two layers: `_run_cached` memoizes the raw hledger subprocess
output on (argv, journal_mtime); `_master_rows_cached` memoizes the *parsed*
master-pull rows per measure on top of that, so repeated get_* calls within a
request don't even re-parse the CSV, let alone re-run the subprocess.
"""
import os
import subprocess
import time

from app.services import hledger as hl
from app.services.query import Measure


def _count_subprocess_calls(fn):
    calls = {"n": 0}
    real_run = subprocess.run

    def counting_run(*args, **kwargs):
        calls["n"] += 1
        return real_run(*args, **kwargs)

    subprocess.run = counting_run
    try:
        fn()
    finally:
        subprocess.run = real_run
    return calls["n"]


def _clear_caches():
    hl._run_cached.cache_clear()
    hl._master_rows_cached.cache_clear()


def test_repeated_call_hits_cache():
    _clear_caches()
    n1 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-12"))
    n2 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-12"))
    assert n1 == 1
    assert n2 == 0


def test_journal_mtime_change_invalidates_cache(tmp_path):
    journal = tmp_path / "j.journal"
    journal.write_text("2024-01-01 * Test\n    expenses:food  10.00 USD\n    assets:checking\n")

    old_file = os.environ["HLEDGER_FILE"]
    os.environ["HLEDGER_FILE"] = str(journal)
    _clear_caches()
    try:
        n1 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-01"))
        assert n1 == 1

        # Same query, unchanged file: cached, zero subprocesses.
        n2 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-01"))
        assert n2 == 0

        # Touch the journal (new mtime) — cache key changes, must re-run.
        time.sleep(0.01)
        journal.write_text(journal.read_text() + "\n2024-01-02 * More\n    expenses:food  5.00 USD\n    assets:checking\n")
        n3 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-01"))
        assert n3 == 1
    finally:
        os.environ["HLEDGER_FILE"] = old_file
        _clear_caches()


def test_master_pull_is_two_calls_regardless_of_page_or_date_range():
    # The whole point of the Option A refactor (PERFORMANCE.md): what used to
    # be up to 17 distinct per-page/per-date-range hledger subprocess
    # invocations is now exactly 2 (one FLOW master pull, one STOCK master
    # pull), shared across every get_* call and every date range.
    _clear_caches()

    def run_several_pages_worth_of_different_date_ranges():
        hl.get_expense_breakdown("2024-01", "2024-12")
        hl.get_expense_category_history("2024-01", "2024-12")
        hl.get_income_breakdown("2024-06", "2024-06")
        hl.get_net_worth_snapshot("2026-07")
        hl.get_net_worth_history("2025-01", "2025-12")
        hl.get_investment_breakdown("2026-07")
        hl.get_asset_breakdown("2026-06")
        hl.get_liability_breakdown("2026-06")
        hl.get_sankey_data("2024-03", "2024-09")

    n = _count_subprocess_calls(run_several_pages_worth_of_different_date_ranges)
    assert n == 2

    # And a second batch of calls, even with yet more new date ranges, costs
    # zero further subprocesses — the master pulls are already cached.
    n2 = _count_subprocess_calls(lambda: hl.get_expense_total("2023-01", "2023-06"))
    assert n2 == 0


def test_master_rows_cached_shields_run_cached():
    # _master_rows_cached memoizes parsed rows on (measure, mtime), on top of
    # _run_cached's (argv, mtime) subprocess-output cache. Clearing only the
    # subprocess-level cache must not force a redundant subprocess call if
    # _master_rows_cached still holds the parsed result for this mtime.
    _clear_caches()
    hl.master_rows(Measure.FLOW)
    hl._run_cached.cache_clear()
    n = _count_subprocess_calls(lambda: hl.master_rows(Measure.FLOW))
    assert n == 0
