"""Shared helpers for date range filter context."""
from datetime import date


def last_month(today: date) -> str:
    m = today.month - 1
    y = today.year
    if m == 0:
        m = 12
        y -= 1
    return f"{y}-{m:02d}"


def last_12_from(today: date) -> str:
    m = today.month - 11
    y = today.year
    if m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


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
