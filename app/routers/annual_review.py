from calendar import month_abbr
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app._templates import templates
from app.services import hledger as hl

router = APIRouter()


@router.get("/annual-review", response_class=HTMLResponse)
async def annual_review(request: Request, year: Optional[int] = None):
    today = date.today()
    all_years = hl.available_years()
    valid_years = [y for y in all_years if y <= today.year]

    selected_year = year or today.year
    if valid_years and selected_year not in valid_years:
        selected_year = valid_years[-1]

    year_from = f"{selected_year}-01"
    year_to   = f"{selected_year}-12" if selected_year < today.year else today.strftime("%Y-%m")
    prior_year  = selected_year - 1
    prior_from  = f"{prior_year}-01"
    prior_to    = f"{prior_year}-12" if selected_year < today.year else f"{prior_year}-{today.month:02d}"

    _empty = {"income": 0.0, "expenses": 0.0, "net": 0.0, "savings_rate": 0.0}
    error = None
    summary = dict(_empty)
    prior_summary = dict(_empty)
    monthly_rows: list[dict] = []
    increases: list[dict] = []
    decreases: list[dict] = []
    nw_start = 0.0
    nw_end   = 0.0
    inv_start = 0.0
    inv_end   = 0.0
    best_month_key: Optional[str] = None
    worst_month_key: Optional[str] = None
    sankey_data: dict = {"nodes": [], "links": []}

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            f_summary       = pool.submit(hl.get_summary, year_from, year_to)
            f_prior_summary = pool.submit(hl.get_summary, prior_from, prior_to)
            f_breakdown     = pool.submit(hl.get_expense_breakdown, year_from, year_to)
            f_prior_bd      = pool.submit(hl.get_expense_breakdown, prior_from, prior_to)
            f_monthly_exp   = pool.submit(hl.get_monthly_expense_totals, year_from, year_to)
            f_monthly_inc   = pool.submit(hl.get_monthly_income_totals, year_from, year_to)
            f_nw            = pool.submit(hl.get_net_worth_history, f"{prior_year}-12", year_to)
            f_invested      = pool.submit(hl.get_monthly_investment_total, f"{prior_year}-12", year_to)
            f_sankey        = pool.submit(hl.get_sankey_data, year_from, year_to)

            summary       = f_summary.result()
            prior_summary = f_prior_summary.result()
            breakdown     = f_breakdown.result()
            prior_bd      = f_prior_bd.result()
            monthly_exp   = f_monthly_exp.result()
            monthly_inc   = f_monthly_inc.result()
            nw_history    = f_nw.result()
            invested_history = f_invested.result()
            sankey_data   = f_sankey.result()

        # Monthly breakdown table
        for m in hl.months_in_range(year_from, year_to):
            inc  = monthly_inc.get(m, 0.0)
            exp  = monthly_exp.get(m, 0.0)
            saved = inc - exp
            sr    = round(saved / inc * 100, 1) if inc > 0 else 0.0
            monthly_rows.append({
                "month":        m,
                "label":        month_abbr[int(m[5:7])],
                "income":       inc,
                "expenses":     exp,
                "saved":        saved,
                "savings_rate": sr,
            })

        with_income = [r for r in monthly_rows if r["income"] > 0]
        if with_income:
            best_month_key  = max(with_income, key=lambda r: r["savings_rate"])["month"]
            worst_month_key = min(with_income, key=lambda r: r["savings_rate"])["month"]

        # Category movers vs prior year
        prior_map = {r["account"]: r["amount"] for r in prior_bd}
        movers = []
        for r in breakdown:
            prior_amt = prior_map.get(r["account"], 0.0)
            delta = r["amount"] - prior_amt
            pct   = delta / prior_amt * 100 if prior_amt > 0 else None
            movers.append({
                "account":    r["account"],
                "amount":     r["amount"],
                "prior":      prior_amt,
                "delta":      delta,
                "pct_change": pct,
            })
        movers.sort(key=lambda x: x["delta"], reverse=True)
        increases = [m for m in movers if m["delta"] > 0][:5]
        decreases = sorted([m for m in movers if m["delta"] < 0], key=lambda x: x["delta"])[:5]

        # Net worth and amount invested, start vs end of year
        prior_dec = f"{prior_year}-12"
        if nw_history:
            start_entry = next((r for r in nw_history if r["month"] == prior_dec), None)
            nw_start    = start_entry["net_worth"] if start_entry else 0.0
            nw_end      = nw_history[-1]["net_worth"]
        inv_start = invested_history.get(prior_dec, 0.0)
        inv_end   = invested_history.get(year_to, 0.0)

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "annual_review.html", {
        "active":           "annual_review",
        "error":            error,
        "selected_year":    selected_year,
        "available_years":  valid_years,
        "prior_year":       prior_year,
        "year_to":          year_to,
        "is_current_year":  selected_year == today.year,
        "summary":          summary,
        "prior_summary":    prior_summary,
        "monthly_rows":     monthly_rows,
        "best_month_key":   best_month_key,
        "worst_month_key":  worst_month_key,
        "increases":        increases,
        "decreases":        decreases,
        "nw_start":         nw_start,
        "nw_end":           nw_end,
        "inv_start":        inv_start,
        "inv_end":          inv_end,
        "sankey_data":      sankey_data,
    })
