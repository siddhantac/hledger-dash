from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import hledger as hl
from app.routers._filters import filter_context

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

VALID_PERIOD_TYPES = {"monthly", "quarterly", "yearly"}


@router.get("/reports", response_class=HTMLResponse)
async def reports(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    period_type: str = "monthly",
    tab: str = "income",
):
    ctx = filter_context(date_from, date_to)
    df, dt = str(ctx["date_from"]), str(ctx["date_to"])

    if period_type not in VALID_PERIOD_TYPES:
        period_type = "monthly"
    if tab not in ("income", "balance"):
        tab = "income"

    error = None
    income_statement: dict = {}
    balance_sheet: dict = {}

    try:
        income_statement = hl.get_income_statement(df, dt, period_type)
        balance_sheet = hl.get_balance_sheet(df, dt, period_type)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "reports.html", {
        "active": "reports",
        "error": error,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "period_type": period_type,
        "tab": tab,
        **ctx,
    })
