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

Переменная окружения `LAUNCHES_DB` переопределяет путь к базе (по умолчанию `./launches.db`).

### Docker

```bash
docker build -t launch-radar .
docker run --rm -p 8000:8000 -v "$PWD/launches.db:/data/launches.db:ro" -e LAUNCHES_DB=/data/launches.db launch-radar
```

### Демо-данные для графика launch_date

```bash
.venv/bin/python scripts/make_demo_db.py   # создаёт demo.db (копию со случайными launch_date)
LAUNCHES_DB=demo.db .venv/bin/uvicorn app.main:app --reload
```

Оригинальная `launches.db` при этом не изменяется.

## AI-выжимка (Fortytwo)

В карточке лаунча кнопка «Сгенерировать» отправляет все упоминания токена в модель `qwen/qwen3.8-27b`
через [Fortytwo API](https://docs.fortytwo.network/) и показывает структурированную выжимку:
что это за токен, какие факты есть в источнике, какие заявления делает проект (с цитатой),
чего в источнике нет, и флаги риска. Ответ — строгий JSON-схема, `reasoning_effort: low`, `temperature: 0`.

Результат кешируется в отдельной базе `radar.db` (переменная `RADAR_DB`); `launches.db` остаётся только для чтения.
Повторная генерация — кнопка «обновить» (`POST …/summary?force=1`).

По умолчанию генерация тяжёлая: `reasoning_effort: max`, до 400 000 символов источников и 60 000 токенов ответа.
Все три параметра переопределяются переменными окружения.

```bash
export FORTYTWO_API_KEY=...          # без ключа дашборд работает, кнопка покажет ошибку
export SUMMARY_LANG=ru               # язык выжимки (по умолчанию ru)
export SUMMARY_REASONING=max         # none|minimal|low|medium|high|xhigh|max
.venv/bin/python -m app.summarize <key>   # проверить одну выжимку из терминала, без веба

# все лаунчи подряд; --force перегенерирует существующие; --loop N повторяет проход каждые N секунд
.venv/bin/python scripts/backfill_summaries.py --workers 4
.venv/bin/python scripts/backfill_summaries.py --force --workers 8 --loop 60
```

В Docker кеш должен лежать на записываемом томе, а не в `/data` (он смонтирован `:ro`):

```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/launches.db:/data/launches.db:ro" -e LAUNCHES_DB=/data/launches.db \
  -v radar-state:/state -e RADAR_DB=/state/radar.db \
  -e FORTYTWO_API_KEY=... launch-radar
```

## API

- `GET /` — дашборд: фильтры (поиск, stage, launchpad) и график за 30 дней
- `GET /api/launches?stage=&launchpad=&q=` — список лаунчей (JSON, без `raw`), сортировка по `seen_at DESC`
- `GET /api/stats?days=30` — `[{date, count}]` по дням
- `GET /api/stats?days=30&by=seen|launch` — по `seen_at` (прошедшие 30 дней) или по `launch_date` (ближайшие 30 дней)
- `GET /api/launches.csv` — экспорт CSV с теми же фильтрами (BOM, открывается в Excel)
- `GET /partials/launches` — HTML-фрагмент таблицы для HTMX (та же фильтрация)
- `GET /launches/{key}` — карточка лаунча (контракт, source, raw JSON)
- `GET /launches/{key}/summary` — HTML-фрагмент с кешированной выжимкой (модель не вызывается)
- `POST /launches/{key}/summary?force=0|1` — сгенерировать выжимку через Fortytwo, закешировать, вернуть фрагмент

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
