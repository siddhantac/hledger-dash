from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()


@router.get("/networth", response_class=HTMLResponse)
async def networth(request: Request, year: Optional[int] = None):
    today = date.today()
    current_year = today.year
    current_month = today.strftime("%Y-%m")

    error = None
    years: list[int] = []
    selected_year = year or current_year
    snapshot = {"liquid": 0.0, "invested": 0.0, "liabilities": 0.0, "net_worth": 0.0}
    asset_breakdown: list[dict] = []
    liability_breakdown: list[dict] = []
    chart_labels: list[str] = []
    chart_assets: list[float] = []
    chart_net_worth: list[float] = []
    table_rows: list[dict] = []

    try:
        years = hl.available_years()
        selected_year = year or current_year
        hist_from = f"{years[0]}-01" if years else f"{current_year}-01"

        # Fire all independent hledger calls in parallel
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_history  = pool.submit(hl.get_net_worth_history, hist_from, current_month)
            f_snapshot = pool.submit(hl.get_net_worth_snapshot, current_month)
            f_assets   = pool.submit(hl.get_asset_breakdown, current_month)
            f_liabs    = pool.submit(hl.get_liability_breakdown, current_month)

            history          = f_history.result()
            snapshot         = f_snapshot.result()
            asset_breakdown  = f_assets.result()
            liability_breakdown = f_liabs.result()

        chart_labels    = [f"{month_abbr[int(r['month'][5:7])]} {r['month'][:4]}" for r in history]
        chart_assets    = [r["assets"] for r in history]
        chart_net_worth = [r["net_worth"] for r in history]

        # Year table derived from full history — no extra hledger call needed
        table_rows = [r for r in history if r["month"].startswith(str(selected_year))]

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "networth.html", {
        "active": "networth",
        "error": error,
        "years": years,
        "selected_year": selected_year,
        "snapshot": snapshot,
        "asset_breakdown": asset_breakdown,
        "liability_breakdown": liability_breakdown,
        "chart_labels": chart_labels,
        "chart_assets": chart_assets,
        "chart_net_worth": chart_net_worth,
        "table_rows": table_rows,
        "date_from": current_month,
        "date_to": current_month,
    })
