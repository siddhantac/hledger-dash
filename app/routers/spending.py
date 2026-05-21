from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()

MONTH_NAMES = [month_abbr[i] for i in range(1, 13)]


def _subtract_year(ym: str) -> str:
    return f"{int(ym[:4]) - 1}{ym[4:]}"


@router.get("/spending", response_class=HTMLResponse)
async def spending(
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

    error = None
    years: list[int] = []
    first_month = f"{today.year}-01"
    breakdown: list[dict] = []
    table_rows: list[dict] = []
    pie_labels: list[str] = []
    pie_amounts: list[float] = []
    total_spend = 0.0
    avg_monthly = 0.0
    trend_labels: list[str] = []
    trend_datasets: list[dict] = []
    heatmap_rows: list[dict] = []
    quarterly_rows: list[dict] = []

    try:
        years = hl.available_years()
        all_from = f"{years[0]}-01" if years else f"{today.year}-01"
        first_month = all_from

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_breakdown = pool.submit(hl.get_expense_breakdown, date_from, date_to)
            f_yoy       = pool.submit(hl.get_expense_breakdown, yoy_from, yoy_to)
            f_history   = pool.submit(hl.get_expense_category_history, all_from, current_month)

            breakdown       = f_breakdown.result()
            yoy_breakdown   = f_yoy.result()
            category_history = f_history.result()

        # ── Period summary ─────────────────────────────────────────────────
        total_spend = sum(r["amount"] for r in breakdown)
        n_months = len(hl.months_in_range(date_from, date_to))
        avg_monthly = total_spend / n_months if n_months else 0.0

        pie_labels  = [r["account"] for r in breakdown[:10]]
        pie_amounts = [r["amount"]  for r in breakdown[:10]]

        # ── Category table with YoY delta ──────────────────────────────────
        yoy_map = {r["account"]: r["amount"] for r in yoy_breakdown}
        for r in breakdown:
            last_year = yoy_map.get(r["account"], 0.0)
            delta = r["amount"] - last_year
            pct_of_total = r["amount"] / total_spend * 100 if total_spend else 0.0
            pct_change: Optional[float] = (delta / last_year * 100) if last_year > 0 else None
            table_rows.append({
                "account":      r["account"],
                "amount":       r["amount"],
                "pct_of_total": pct_of_total,
                "last_year":    last_year,
                "delta":        delta,
                "pct_change":   pct_change,
            })

        # ── Monthly totals across all time (heat map + quarterly source) ───
        monthly_totals: dict[str, float] = {}
        for cat_data in category_history.values():
            for month, amount in cat_data.items():
                monthly_totals[month] = monthly_totals.get(month, 0.0) + amount

        # ── Heat map ───────────────────────────────────────────────────────
        max_monthly = max(monthly_totals.values(), default=1.0)
        for y in reversed(years):
            months_data = []
            for m_num in range(1, 13):
                ym = f"{y}-{m_num:02d}"
                amount = monthly_totals.get(ym, 0.0)
                intensity = min(amount / max_monthly, 1.0) if max_monthly else 0.0
                months_data.append({"amount": amount, "intensity": intensity})
            heatmap_rows.append({"year": y, "months": months_data})

        # ── Quarterly rollup ───────────────────────────────────────────────
        for y in reversed(years):
            quarters = [0.0, 0.0, 0.0, 0.0]
            for m_num in range(1, 13):
                quarters[(m_num - 1) // 3] += monthly_totals.get(f"{y}-{m_num:02d}", 0.0)
            quarterly_rows.append({
                "year":    y,
                "quarters": quarters,
                "total":   sum(quarters),
            })

        # ── Category trend chart (top 5 categories, all time) ──────────────
        top_cats = [r["account"] for r in breakdown[:5]]
        all_months = sorted(monthly_totals.keys())
        trend_labels = [f"{month_abbr[int(m[5:7])]} {m[:4]}" for m in all_months]
        trend_datasets = [
            {
                "label": cat.capitalize(),
                "data": [category_history.get(cat, {}).get(m, 0.0) for m in all_months],
            }
            for cat in top_cats
        ]

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "spending.html", {
        "active":          "spending",
        "error":           error,
        "date_from":       date_from,
        "date_to":         date_to,
        "total_spend":     total_spend,
        "avg_monthly":     avg_monthly,
        "pie_labels":      pie_labels,
        "pie_amounts":     pie_amounts,
        "table_rows":      table_rows,
        "trend_labels":    trend_labels,
        "trend_datasets":  trend_datasets,
        "heatmap_rows":    heatmap_rows,
        "quarterly_rows":  quarterly_rows,
        "month_names":     MONTH_NAMES,
        "first_month":     first_month,
    })
