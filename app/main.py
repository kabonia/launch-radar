from pathlib import Path

import csv
import io

from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import db, summarize

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
def api_stats(days: int = 30, by: str = "seen"):
    if by not in ("seen", "launch"):
        raise HTTPException(status_code=400, detail="by must be 'seen' or 'launch'")
    direction = "future" if by == "launch" else "past"
    return db.get_stats_by_day(db.STATS_COLUMN_BY_MODE[by], days, direction)


@app.get("/api/launches.csv")
def api_launches_csv(stage: str | None = None, launchpad: str | None = None, q: str | None = None):
    rows = db.get_launches(stage=_clean(stage), launchpad=_clean(launchpad), q=_clean(q))
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=db.LAUNCH_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="launches.csv"'},
    )


@app.get("/")
def index(request: Request):
    options = db.get_filter_options()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"launches": db.get_launches(), "options": options},
    )


@app.get("/launches/{key}", response_class=HTMLResponse)
def launch_detail(request: Request, key: str):
    launch = db.get_launch(key)
    if launch is None:
        raise HTTPException(status_code=404, detail="launch not found")
    return templates.TemplateResponse(request, "detail.html", {"launch": launch})


def _render_summary(request: Request, key: str, summary: dict | None = None, error: str | None = None):
    launch = db.get_launch(key)
    if launch is None:
        raise HTTPException(status_code=404, detail="launch not found")
    return templates.TemplateResponse(
        request,
        "partials/summary.html",
        {"launch": launch, "summary": summary, "error": error, "flag_labels": summarize.FLAG_LABELS},
    )


@app.get("/launches/{key}/summary", response_class=HTMLResponse)
def launch_summary(request: Request, key: str):
    """Cached brief only; never calls the model."""
    return _render_summary(request, key, summarize.get_cached(key))


@app.post("/launches/{key}/summary", response_class=HTMLResponse)
def launch_summary_generate(request: Request, key: str, force: bool = False):
    """Generate (or regenerate with ?force=1) the brief via Fortytwo and cache it."""
    try:
        data = summarize.generate(key, force=force)
    except KeyError:
        raise HTTPException(status_code=404, detail="launch not found")
    except Exception as e:  # no key, 402, rate limit, invalid JSON -> show inline, keep the page alive
        return _render_summary(request, key, error=f"{type(e).__name__}: {str(e)[:200]}")
    return _render_summary(request, key, data)


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
