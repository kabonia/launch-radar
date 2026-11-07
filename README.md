# Launch Radar

Веб-дашборд поверх существующей SQLite-базы `launches.db` (только чтение).

Стек: Python 3.12+, FastAPI, Jinja2, HTMX, Chart.js (CDN). Без сборки фронта.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Открыть http://127.0.0.1:8000

## API

- `GET /` — дашборд: фильтры (поиск, stage, launchpad) и график за 30 дней
- `GET /api/launches?stage=&launchpad=&q=` — список лаунчей (JSON, без `raw`), сортировка по `seen_at DESC`
- `GET /api/stats?days=30` — `[{date, count}]` по дням
- `GET /api/stats?days=30&by=seen|launch` — по `seen_at` (прошедшие 30 дней) или по `launch_date` (ближайшие 30 дней)
- `GET /api/launches.csv` — экспорт CSV с теми же фильтрами (BOM, открывается в Excel)
- `GET /partials/launches` — HTML-фрагмент таблицы для HTMX (та же фильтрация)
- `GET /launches/{key}` — карточка лаунча (контракт, source, raw JSON)

Таблица на `/` автообновляется раз в 30 секунд с учётом текущих фильтров.

## Структура

```
app/
├── main.py          # роутеры
├── db.py            # read-only SQLite (file:...?mode=ro), запросы
└── templates/
    ├── base.html
    ├── index.html
    └── partials/launch_table.html
```
