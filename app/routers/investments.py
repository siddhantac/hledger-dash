from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()


@router.get("/investments", response_class=HTMLResponse)
async def investments(request: Request):
    today = date.today()
    current_month = today.strftime("%Y-%m")

    error = None
    breakdown: list[dict] = []
    pie_labels: list[str] = []
    pie_amounts: list[float] = []
    holdings_rows: list[dict] = []
    total_invested = 0.0
    top_holding: dict = {}
    yoy_pct_change: Optional[float] = None
    chart_labels: list[str] = []
    chart_data: list[float] = []
    annual_rows: list[dict] = []

    try:
        years = hl.available_years()
        all_from = f"{years[0]}-01" if years else f"{today.year}-01"

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_breakdown = pool.submit(hl.get_investment_breakdown, current_month)
            f_monthly   = pool.submit(hl.get_monthly_investment_total, all_from, current_month)

            breakdown    = f_breakdown.result()
            monthly_totals = f_monthly.result()

        # Summary
        total_invested = sum(r["amount"] for r in breakdown)
        top_holding = breakdown[0] if breakdown else {}

        pie_labels  = [r["account"] for r in breakdown]
        pie_amounts = [r["amount"]  for r in breakdown]

        # Holdings table with % share
        for r in breakdown:
            holdings_rows.append({
                "account":      r["account"],
                "full_account": r["full_account"],
                "amount":       r["amount"],
                "pct":          r["amount"] / total_invested * 100 if total_invested else 0.0,
            })

        # Monthly history chart
        all_months = sorted(monthly_totals.keys())
        chart_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in all_months]
        chart_data   = [monthly_totals.get(m, 0.0) for m in all_months]

        # Annual summary table (end-of-year balance per year)
        prev_total = 0.0
        for y in years:
            end_key = f"{y}-12" if y < today.year else current_month
            total = monthly_totals.get(end_key, 0.0)
            change = total - prev_total if prev_total > 0 else None
            pct_change = (change / prev_total * 100) if (prev_total > 0 and change is not None) else None
            annual_rows.append({
                "year":       y,
                "total":      total,
                "change":     change,
                "pct_change": pct_change,
                "is_current": y == today.year,
            })
            prev_total = total

        # YoY card: current total vs end of last year
        last_year_total = monthly_totals.get(f"{today.year - 1}-12", 0.0)
        if last_year_total > 0:
            yoy_pct_change = (total_invested - last_year_total) / last_year_total * 100

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "investments.html", {
        "active":          "investments",
        "error":           error,
        "total_invested":  total_invested,
        "top_holding":     top_holding,
        "yoy_pct_change":  yoy_pct_change,
        "pie_labels":      pie_labels,
        "pie_amounts":     pie_amounts,
        "holdings_rows":   holdings_rows,
        "chart_labels":    chart_labels,
        "chart_data":      chart_data,
        "annual_rows":     annual_rows,
        "current_month":   current_month,
    })
