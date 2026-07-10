import os
import time

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


def _last_synced() -> str:
    path = os.environ.get("HLEDGER_FILE", "")
    if not path:
        return ""
    try:
        minutes = int((time.time() - os.path.getmtime(path)) / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except OSError:
        return ""


templates.env.filters["fmt"] = _fmt
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.globals["last_synced"] = _last_synced
