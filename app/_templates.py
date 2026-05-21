from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def _fmt(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


templates.env.filters["fmt"] = _fmt
templates.env.filters["fmt_pct"] = _fmt_pct
