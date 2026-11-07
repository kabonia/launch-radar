import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "launches.db"

LAUNCH_COLUMNS = (
    "key",
    "ticker",
    "name",
    "chain",
    "contract",
    "launchpad",
    "stage",
    "launch_date",
    "confidence",
    "source",
    "seen_at",
)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def get_launches(stage: str | None = None, launchpad: str | None = None, q: str | None = None) -> list[dict]:
    query = f"SELECT {", ".join(LAUNCH_COLUMNS)} FROM events"
    conditions: list[str] = []
    params: list[str] = []
    if stage:
        conditions.append("stage = ?")
        params.append(stage)
    if launchpad:
        conditions.append("launchpad = ?")
        params.append(launchpad)
    if q:
        like = f"%{q}%"
        conditions.append("(ticker LIKE ? OR name LIKE ?)")
        params.extend((like, like))
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY seen_at DESC"

    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(zip(LAUNCH_COLUMNS, row)) for row in rows]


def get_stats_30d(days: int = 30) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT date(seen_at), COUNT(*) FROM events "
            "WHERE date(seen_at) >= date('now', ?) GROUP BY date(seen_at)",
            (f"-{days - 1} days",),
        ).fetchall()
    counts = {day: count for day, count in rows}
    today = datetime.now(timezone.utc).date()
    result: list[dict] = []
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        result.append({"date": key, "count": counts.get(key, 0)})
    return result


def get_filter_options() -> dict[str, list[str]]:
    with closing(_connect()) as conn:
        stages = [row[0] for row in conn.execute("SELECT DISTINCT stage FROM events WHERE stage != '' ORDER BY stage")]
        launchpads = [row[0] for row in conn.execute("SELECT DISTINCT launchpad FROM events WHERE launchpad != '' ORDER BY launchpad")]
    return {"stage": stages, "launchpad": launchpads}


def get_launch(key: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {', '.join(LAUNCH_COLUMNS)}, raw FROM events WHERE key = ?", (key,)
        ).fetchone()
    return dict(zip(LAUNCH_COLUMNS + ("raw",), row)) if row else None
