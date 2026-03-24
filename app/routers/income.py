from calendar import month_abbr
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import hledger as hl
from app.routers._filters import filter_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/income", response_class=HTMLResponse)
async def income(request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None):
    ctx = filter_context(date_from, date_to)
    df, dt = str(ctx["date_from"]), str(ctx["date_to"])

    error = None
    breakdown = []
    monthly_income = []
    chart_labels = []

    try:
        breakdown = hl.get_income_breakdown(df, dt)
        months = hl.months_in_range(df, dt)
        income_totals = hl.get_monthly_totals(df, dt, "income")
        chart_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in months]
        monthly_income = [income_totals.get(m, 0) for m in months]
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "income.html", {
        "active": "income",
        "error": error,
        "breakdown": breakdown,
        "pie_labels": [r["account"] for r in breakdown],
        "pie_amounts": [r["amount"] for r in breakdown],
        "chart_labels": chart_labels,
        "monthly_income": monthly_income,
        **ctx,
    })
