import functools
import os
import subprocess
import time
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

# app/_templates.py -> app/ -> project root (matches Docker's WORKDIR /app, where
# the VERSION file baked in by the Dockerfile's `version` build stage also lands).
_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


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


@functools.lru_cache(maxsize=1)
def _version() -> str:
    env_version = os.environ.get("APP_VERSION")
    if env_version:
        return env_version
    try:
        file_version = _VERSION_FILE.read_text().strip()
        if file_version:
            return file_version
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


templates.env.filters["fmt"] = _fmt
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.globals["last_synced"] = _last_synced
templates.env.globals["version"] = _version
