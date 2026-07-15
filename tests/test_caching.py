"""Phase 2: run_hledger caches on (argv, journal_mtime) — verifies V2.2."""
import os
import subprocess
import time

from app.services import hledger as hl


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


def test_repeated_call_hits_cache():
    hl._run_cached.cache_clear()
    n1 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-12"))
    n2 = _count_subprocess_calls(lambda: hl.get_expense_total("2024-01", "2024-12"))
    assert n1 == 1
    assert n2 == 0


def test_journal_mtime_change_invalidates_cache(tmp_path):
    journal = tmp_path / "j.journal"
    journal.write_text("2024-01-01 * Test\n    expenses:food  10.00 USD\n    assets:checking\n")

    old_file = os.environ["HLEDGER_FILE"]
    os.environ["HLEDGER_FILE"] = str(journal)
    hl._run_cached.cache_clear()
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
        hl._run_cached.cache_clear()
