from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.routers._filters import last_12_from, last_month
from app.services import hledger as hl

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
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

    ytd_from = f"{today.year}-01"
    last12_from = last_12_from(today)
    last_month_val = last_month(today)

    error = None
    _empty = {"income": 0.0, "expenses": 0.0, "net": 0.0, "savings_rate": 0.0}
    period_summary = dict(_empty)
    last_month_summary = dict(_empty)
    ytd_summary = dict(_empty)
    trailing_summary = dict(_empty)
    net_worth = 0.0
    first_month = f"{today.year}-01"
    chart_labels: list[str] = []
    monthly_income: list[float] = []
    monthly_expenses: list[float] = []
    savings_rate_data: list[float] = []

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            f_period     = pool.submit(hl.get_summary, date_from, date_to)
            f_lastmonth  = pool.submit(hl.get_summary, last_month_val, last_month_val)
            f_ytd        = pool.submit(hl.get_summary, ytd_from, current_month)
            f_trailing   = pool.submit(hl.get_summary, last12_from, current_month)
            f_networth   = pool.submit(hl.get_net_worth_snapshot, current_month)
            f_inc_hist   = pool.submit(hl.get_monthly_income_totals, last12_from, current_month)
            f_exp_hist   = pool.submit(hl.get_monthly_expense_totals, last12_from, current_month)
            f_years      = pool.submit(hl.available_years)

            period_summary      = f_period.result()
            last_month_summary  = f_lastmonth.result()
            ytd_summary         = f_ytd.result()
            trailing_summary    = f_trailing.result()
            net_worth           = f_networth.result()["net_worth"]
            inc_hist            = f_inc_hist.result()
            exp_hist            = f_exp_hist.result()
            years               = f_years.result()
            if years:
                first_month = f"{years[0]}-01"

        months = hl.months_in_range(last12_from, current_month)
        chart_labels    = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in months]
        monthly_income   = [inc_hist.get(m, 0.0) for m in months]
        monthly_expenses = [exp_hist.get(m, 0.0) for m in months]
        savings_rate_data = [
            round((inc - exp) / inc * 100, 1) if inc > 0 else 0.0
            for inc, exp in zip(monthly_income, monthly_expenses)
        ]

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "dashboard.html", {
        "active":             "dashboard",
        "error":              error,
        "date_from":          date_from,
        "date_to":            date_to,
        "period_summary":     period_summary,
        "last_month_summary":  last_month_summary,
        "last_month":          last_month_val,
        "ytd_summary":        ytd_summary,
        "trailing_summary":   trailing_summary,
        "net_worth":          net_worth,
        "chart_labels":       chart_labels,
        "monthly_income":     monthly_income,
        "monthly_expenses":   monthly_expenses,
        "savings_rate_data":  savings_rate_data,
        "current_month":      current_month,
        "first_month":        first_month,
    })
