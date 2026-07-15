from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.routers._filters import last_month
from app.services import hledger as hl

router = APIRouter()


@router.get("/transactions", response_class=HTMLResponse)
async def transactions(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    today = date.today()
    last_month_val = last_month(today)
    date_from = date_from or last_month_val
    date_to   = date_to   or last_month_val
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    error = None
    txns: list[dict] = []
    first_month = f"{today.year}-01"

    try:
        years = hl.available_years()
        if years:
            first_month = f"{years[0]}-01"
        txns = hl.get_transactions(date_from, date_to)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "transactions.html", {
        "active":       "transactions",
        "error":        error,
        "date_from":    date_from,
        "date_to":      date_to,
        "first_month":  first_month,
        "txns":         txns,
        "txn_count":    len(txns),
    })
