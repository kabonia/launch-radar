from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Launch Radar")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _plural(n: int, one: str, few: str, many: str) -> str:
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return f"{n} {one}"
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


templates.env.filters["plural"] = _plural


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@app.get("/api/launches")
def api_launches(stage: str | None = None, launchpad: str | None = None, q: str | None = None):
    return db.get_launches(stage=_clean(stage), launchpad=_clean(launchpad), q=_clean(q))


@app.get("/api/stats")
def api_stats(days: int = 30):
    return db.get_stats_30d(days)


@app.get("/")
def index(request: Request):
    options = db.get_filter_options()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"launches": db.get_launches(), "options": options},
    )


@app.get("/partials/launches", response_class=HTMLResponse)
def launches_partial(
    request: Request,
    stage: str | None = None,
    launchpad: str | None = None,
    q: str | None = None,
):
    return templates.TemplateResponse(
        request,
        "partials/launch_table.html",
        {"launches": db.get_launches(stage=_clean(stage), launchpad=_clean(launchpad), q=_clean(q))},
    )
