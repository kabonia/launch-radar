"""Создаёт копию launches.db со случайными launch_date для проверки графика.

Оригинальная БД не изменяется (требование: только чтение).
Запуск: .venv/bin/python scripts/make_demo_db.py [out_path]
"""
import random
import shutil
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "launches.db"
DEFAULT_OUT = ROOT / "demo.db"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    shutil.copyfile(SOURCE, out)
    today = date.today()
    conn = sqlite3.connect(out)
    try:
        count = 0
        for row_id, in conn.execute(
            "SELECT rowid FROM events WHERE launch_date IS NULL OR launch_date = ''"
        ):
            if random.random() < 0.25:
                continue  # часть строк оставляем без даты
            launch_day = (today + timedelta(days=random.randint(0, 29))).isoformat()
            conn.execute("UPDATE events SET launch_date = ? WHERE rowid = ?", (launch_day, row_id))
            count += 1
        conn.commit()
        print(f"demo db: {out} ({count} строк со случайным launch_date за ближайшие 30 дней)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
