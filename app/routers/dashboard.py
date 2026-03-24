from calendar import month_abbr
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import hledger as hl
from app.routers._filters import filter_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None):
    ctx = filter_context(date_from, date_to)
    df, dt = str(ctx["date_from"]), str(ctx["date_to"])

    error = None
    summary = {"income": 0, "expenses": 0, "net": 0}
    monthly_income = []
    monthly_expenses = []
    chart_labels = []

    try:
        summary = hl.get_summary(df, dt)
        months = hl.months_in_range(df, dt)
        income_totals = hl.get_monthly_totals(df, dt, "income")
        expense_totals = hl.get_monthly_totals(df, dt, "expenses")
        chart_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in months]
        monthly_income = [income_totals.get(m, 0) for m in months]
        monthly_expenses = [expense_totals.get(m, 0) for m in months]
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "dashboard.html", {
        "active": "dashboard",
        "error": error,
        "summary": summary,
        "chart_labels": chart_labels,
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        **ctx,
    })
