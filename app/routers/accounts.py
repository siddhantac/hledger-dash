import concurrent.futures
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()


def _last_month() -> str:
    today = date.today()
    m = today.month - 1 or 12
    y = today.year if today.month > 1 else today.year - 1
    return f"{y}-{m:02d}"


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_view(
    request: Request,
    account: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    lm = _last_month()
    date_from = date_from or lm
    date_to   = date_to   or lm
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    error = None
    account_list: dict[str, list[str]] = {"assets": [], "liabilities": []}
    register: list[dict] = []
    first_month = f"{date.today().year}-01"

    try:
        with concurrent.futures.ThreadPoolExecutor() as ex:
            f_years    = ex.submit(hl.available_years)
            f_accounts = ex.submit(hl.get_account_list)
            years        = f_years.result()
            account_list = f_accounts.result()

        if years:
            first_month = f"{years[0]}-01"

        all_accounts = account_list["assets"] + account_list["liabilities"]
        if not account and all_accounts:
            account = all_accounts[0]

        if account:
            register = hl.get_account_register(account, date_from, date_to)

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "accounts.html", {
        "active":       "accounts",
        "error":        error,
        "date_from":    date_from,
        "date_to":      date_to,
        "first_month":  first_month,
        "account_list": account_list,
        "selected":     account or "",
        "register":     register,
        "txn_count":    len(register),
    })
