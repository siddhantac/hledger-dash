"""Shared helpers for date range filter context."""
from datetime import date


def filter_context(date_from: str | None, date_to: str | None) -> dict:
    today = date.today()
    current_month = today.strftime("%Y-%m")

    date_from = date_from or current_month
    date_to = date_to or current_month

    # Ensure from <= to
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    return {
        "date_from": date_from,
        "date_to": date_to,
    }
