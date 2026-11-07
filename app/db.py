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


STATS_COLUMN_BY_MODE = {"seen": "seen_at", "launch": "launch_date"}


def get_stats_30d(days: int = 30) -> list[dict]:
    return get_stats_by_day("seen_at", days, "past")


def get_stats_by_day(column: str, days: int = 30, direction: str = "past") -> list[dict]:
    today = datetime.now(timezone.utc).date()
    start = today if direction == "future" else today - timedelta(days=days - 1)
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT date({column}), COUNT(*) FROM events "
            f"WHERE {column} != '' AND date({column}) >= ? "
            f"GROUP BY date({column})",
            (start.isoformat(),),
        ).fetchall()
    counts = {day: count for day, count in rows}
    result: list[dict] = []
    for offset in range(days):
        key = (start + timedelta(days=offset)).isoformat()
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
