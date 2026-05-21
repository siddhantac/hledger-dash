from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()


def _subtract_year(ym: str) -> str:
    return f"{int(ym[:4]) - 1}{ym[4:]}"


def _last_month(today: date) -> str:
    m = today.month - 1
    y = today.year
    if m == 0:
        m = 12
        y -= 1
    return f"{y}-{m:02d}"


def _last_12_from(today: date) -> str:
    m = today.month - 11
    y = today.year
    if m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


@router.get("/income", response_class=HTMLResponse)
async def income(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    today = date.today()
    current_month = today.strftime("%Y-%m")
    date_from = date_from or f"{today.year}-01"
    date_to = date_to or current_month
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    yoy_from = _subtract_year(date_from)
    yoy_to   = _subtract_year(date_to)
    last_month  = _last_month(today)
    last12_from = _last_12_from(today)

    error = None
    breakdown: list[dict] = []
    table_rows: list[dict] = []
    pie_labels: list[str] = []
    pie_amounts: list[float] = []
    total_income = 0.0
    avg_monthly = 0.0
    yoy_total = 0.0
    yoy_pct_change: Optional[float] = None
    last_month_income = 0.0
    trend_labels: list[str] = []
    trend_data: list[float] = []
    savings_labels: list[str] = []
    savings_rate_data: list[float] = []
    first_month = f"{today.year}-01"

    try:
        years = hl.available_years()
        all_from = f"{years[0]}-01" if years else f"{today.year}-01"
        first_month = all_from

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_breakdown = pool.submit(hl.get_income_breakdown, date_from, date_to)
            f_yoy       = pool.submit(hl.get_income_breakdown, yoy_from, yoy_to)
            f_inc_hist  = pool.submit(hl.get_monthly_income_totals, all_from, current_month)
            f_exp_hist  = pool.submit(hl.get_monthly_expense_totals, last12_from, current_month)

            breakdown     = f_breakdown.result()
            yoy_breakdown = f_yoy.result()
            inc_hist      = f_inc_hist.result()
            exp_hist      = f_exp_hist.result()

        # Period summary
        total_income = sum(r["amount"] for r in breakdown)
        n_months = len(hl.months_in_range(date_from, date_to))
        avg_monthly = total_income / n_months if n_months else 0.0

        pie_labels  = [r["account"] for r in breakdown[:10]]
        pie_amounts = [r["amount"]  for r in breakdown[:10]]

        # YoY summary card
        yoy_total = sum(r["amount"] for r in yoy_breakdown)
        if yoy_total > 0:
            yoy_pct_change = (total_income - yoy_total) / yoy_total * 100

        # Last month (derived from all-time history)
        last_month_income = inc_hist.get(last_month, 0.0)

        # Source table with YoY delta
        yoy_map = {r["account"]: r["amount"] for r in yoy_breakdown}
        for r in breakdown:
            last_yr = yoy_map.get(r["account"], 0.0)
            delta = r["amount"] - last_yr
            pct_of_total = r["amount"] / total_income * 100 if total_income else 0.0
            pct_change: Optional[float] = (delta / last_yr * 100) if last_yr > 0 else None
            table_rows.append({
                "account":      r["account"],
                "amount":       r["amount"],
                "pct_of_total": pct_of_total,
                "last_year":    last_yr,
                "delta":        delta,
                "pct_change":   pct_change,
            })

        # All-time monthly trend
        all_months = sorted(inc_hist.keys())
        trend_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in all_months]
        trend_data   = [inc_hist.get(m, 0.0) for m in all_months]

        # Savings rate trend (last 12 months)
        last12_months = hl.months_in_range(last12_from, current_month)
        savings_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in last12_months]
        savings_rate_data = [
            round((inc_hist.get(m, 0.0) - exp_hist.get(m, 0.0)) / inc_hist.get(m, 0.0) * 100, 1)
            if inc_hist.get(m, 0.0) > 0 else 0.0
            for m in last12_months
        ]

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "income.html", {
        "active":             "income",
        "error":              error,
        "date_from":          date_from,
        "date_to":            date_to,
        "total_income":       total_income,
        "avg_monthly":        avg_monthly,
        "yoy_total":          yoy_total,
        "yoy_pct_change":     yoy_pct_change,
        "last_month_income":  last_month_income,
        "last_month":         last_month,
        "pie_labels":         pie_labels,
        "pie_amounts":        pie_amounts,
        "table_rows":         table_rows,
        "trend_labels":       trend_labels,
        "trend_data":         trend_data,
        "savings_labels":     savings_labels,
        "savings_rate_data":  savings_rate_data,
        "first_month":        first_month,
    })
