from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import hledger as hl
from app.routers._filters import filter_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/expenses", response_class=HTMLResponse)
async def expenses(request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None):
    ctx = filter_context(date_from, date_to)
    df, dt = str(ctx["date_from"]), str(ctx["date_to"])

    error = None
    breakdown = []

    try:
        breakdown = hl.get_expense_breakdown(df, dt)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "expenses.html", {
        "active": "expenses",
        "error": error,
        "breakdown": breakdown,
        "chart_labels": [r["account"] for r in breakdown],
        "chart_amounts": [r["amount"] for r in breakdown],
        **ctx,
    })
