"""AI brief for a launch, generated on demand via the Fortytwo API and cached.

launches.db stays read-only. Summaries live in a separate SQLite file that the
dashboard owns (RADAR_DB), so the extractor's database is never written to.

Env:
  FORTYTWO_API_KEY            required to generate; without it the UI shows a hint
  RADAR_DB                    writable SQLite for the cache (default: radar.db next to launches.db)
  SUMMARY_LANG                language for the brief text (default: ru)
  SUMMARY_REASONING           reasoning effort, default max
  SUMMARY_MAX_SOURCE_CHARS    source text budget per brief, default 400000
  SUMMARY_MAX_OUTPUT_TOKENS   max_tokens for the response, default 60000

CLI check without the web app:  .venv/bin/python -m app.summarize <launch key>
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app import db

MODEL = "qwen/qwen3.8-27b"
BASE_URL = "https://api.fortytwo.network/v1"
# Generation knobs (env-overridable). Defaults are deliberately heavy: max reasoning, big budgets.
REASONING_EFFORT = os.environ.get("SUMMARY_REASONING", "max")      # none|minimal|low|medium|high|xhigh|max
MAX_SOURCE_CHARS = int(os.environ.get("SUMMARY_MAX_SOURCE_CHARS", 400_000))   # ~100k tokens of sources
MAX_OUTPUT_TOKENS = int(os.environ.get("SUMMARY_MAX_OUTPUT_TOKENS", 60_000))  # reasoning counts towards this

RISK_FLAGS = (
    "no_contract_address",
    "no_launch_date",
    "unrealistic_returns",
    "urgency_pressure",
    "anonymous_or_unverified_team",
    "mimics_known_brand",
    "presale_without_product",
    "single_source_only",
    "insufficient_information",
)

FLAG_LABELS = {
    "no_contract_address": "нет адреса контракта",
    "no_launch_date": "нет даты запуска",
    "unrealistic_returns": "обещания доходности",
    "urgency_pressure": "давление срочностью",
    "anonymous_or_unverified_team": "команда не раскрыта",
    "mimics_known_brand": "похоже на известный бренд",
    "presale_without_product": "пресейл без продукта",
    "single_source_only": "единственный источник",
    "insufficient_information": "мало данных",
}


# ---------- Output contract ----------
# The JSON schema is written by hand (no $defs/$ref) so strict mode accepts it;
# the pydantic model validates what comes back.

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "facts", "claims", "not_stated", "risk_flags", "data_sufficiency", "confidence"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 neutral sentences: what the token/project is, based only on the source text.",
        },
        "facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete facts literally present in the source: platform, chain, stage, dates, numbers. Empty if none.",
        },
        "claims": {
            "type": "array",
            "description": "Promises, plans and marketing statements the project makes. Empty if none.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence"],
                "properties": {
                    "text": {"type": "string", "description": "The claim, briefly paraphrased."},
                    "evidence": {
                        "type": "string",
                        "description": "Verbatim quote from the source, at most 12 words, that contains this claim.",
                    },
                },
            },
        },
        "not_stated": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Important things the source does NOT mention: team, utility, tokenomics, audit, contract, date.",
        },
        "risk_flags": {
            "type": "array",
            "items": {"type": "string", "enum": list(RISK_FLAGS)},
            "description": "Only flags directly supported by the source text.",
        },
        "data_sufficiency": {
            "type": "string",
            "enum": ["enough", "thin", "insufficient"],
            "description": "How much the source text actually says about the project.",
        },
        "confidence": {
            "type": "number",
            "description": "0..1 - how well the source text supports this brief.",
        },
    },
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "launch_brief", "schema": RESPONSE_SCHEMA, "strict": True},
}


class Claim(BaseModel):
    text: str
    evidence: str


class LaunchBrief(BaseModel):
    summary: str
    facts: list[str]
    claims: list[Claim]
    not_stated: list[str]
    risk_flags: list[Literal[RISK_FLAGS]]  # type: ignore[valid-type]
    data_sufficiency: Literal["enough", "thin", "insufficient"]
    confidence: float = Field(ge=0, le=1)


SYSTEM_PROMPT = """You write short, neutral briefs about crypto token launches for an analytics dashboard.

Rules:
1. Use ONLY the source text in the user message. You have no outside knowledge about this project. If a project with the same name or ticker exists in your training data, ignore it: this may be a different project or a copycat.
2. Every item in `facts` must be literally present in the source. Every claim must carry a short verbatim quote in `evidence`; if you cannot quote it, it is not a claim - drop it.
3. A promise, plan or marketing statement is a claim, never a fact. Never upgrade a claim into a fact.
4. Do not invent numbers, dates, addresses, team members, partners or audits. If the source does not say, put the topic into `not_stated`.
5. Do not give investment advice and do not predict price. Describe, do not recommend.
6. If the source is only a launchpad record (symbol, name, address, curve percentage) with no description, say exactly that in `summary`, set `data_sufficiency` to "insufficient" and add the "insufficient_information" flag.
7. Keep tickers, contract addresses and project names exactly as written in the source.
"""


# ---------- Cache (dashboard-owned SQLite) ----------

def _cache_path() -> Path:
    override = os.environ.get("RADAR_DB")
    return Path(override) if override else db.DB_PATH.parent / "radar.db"


def _cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path(), timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS summaries ("
        "key TEXT PRIMARY KEY, summary_json TEXT NOT NULL, model TEXT, reasoning TEXT, "
        "prompt_tokens INTEGER, completion_tokens INTEGER, created_at TEXT)"
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(summaries)")}
    if "reasoning" not in cols:  # radar.db created by an earlier version
        conn.execute("ALTER TABLE summaries ADD COLUMN reasoning TEXT")
    return conn


def _with_meta(brief: LaunchBrief, model: str, reasoning: str | None,
               prompt_tokens, completion_tokens, created_at: str) -> dict:
    data = brief.model_dump()
    data["meta"] = {
        "model": model,
        "reasoning": reasoning,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "created_at": created_at,
    }
    return data


def get_cached(key: str) -> dict | None:
    with closing(_cache()) as conn:
        row = conn.execute(
            "SELECT summary_json, model, reasoning, prompt_tokens, completion_tokens, created_at "
            "FROM summaries WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    return _with_meta(LaunchBrief.model_validate_json(row[0]), row[1], row[2], row[3], row[4], row[5])


def cache_stats() -> dict:
    """Totals over the cache: briefs, tokens, estimated spend (list prices, cache discount ignored)."""
    with closing(_cache()) as conn:
        n, p, c = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0) FROM summaries"
        ).fetchone()
    return {"briefs": n, "prompt_tokens": p, "completion_tokens": c,
            "est_usd": round(p / 1e6 * 0.425 + c / 1e6 * 2.55, 4)}


def _store(key: str, brief: LaunchBrief, prompt_tokens, completion_tokens, created_at: str) -> None:
    with closing(_cache()) as conn:
        conn.execute(
            "INSERT INTO summaries(key, summary_json, model, reasoning, prompt_tokens, completion_tokens, created_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET summary_json=excluded.summary_json, model=excluded.model, "
            "reasoning=excluded.reasoning, prompt_tokens=excluded.prompt_tokens, "
            "completion_tokens=excluded.completion_tokens, created_at=excluded.created_at",
            (key, brief.model_dump_json(), MODEL, REASONING_EFFORT, prompt_tokens, completion_tokens, created_at),
        )
        conn.commit()


# ---------- Source text ----------

def _source_texts(launch: dict) -> list[tuple[str, str, str]]:
    """(source, seen_at, text). All mentions if the extractor has a `mentions` table, else the event's raw."""
    texts: list[tuple[str, str, str]] = []
    with closing(db._connect()) as conn:
        has_mentions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mentions'"
        ).fetchone()
        if has_mentions:
            rows = conn.execute(
                "SELECT source, seen_at, raw_text FROM mentions WHERE event_key = ? ORDER BY seen_at",
                (launch["key"],),
            ).fetchall()
            texts = [(s or "", t or "", r or "") for s, t, r in rows if r]
    if not texts and launch.get("raw"):
        texts = [(launch.get("source") or "", launch.get("seen_at") or "", launch["raw"])]
    return texts


def build_user_message(launch: dict, texts: list[tuple[str, str, str]], lang: str) -> str:
    record = "\n".join(
        f"{k}: {launch.get(k) or 'null'}"
        for k in ("ticker", "name", "chain", "contract", "launchpad", "stage", "launch_date", "seen_at")
    )
    parts = [
        f"Write `summary`, `facts`, `claims.text` and `not_stated` in this language: {lang}. "
        "Keep `evidence` quotes in the original language of the source.",
        "",
        "Launch record from the extractor (structured, may be incomplete):",
        record,
        "",
        f"Source texts ({len(texts)}):",
    ]
    budget = MAX_SOURCE_CHARS
    for i, (source, seen_at, text) in enumerate(texts, 1):
        chunk = text[:budget]
        budget -= len(chunk)
        parts.append(f"--- source {i} [{source} {seen_at[:16]}] ---\n{chunk}")
        if budget <= 0:
            parts.append("--- remaining sources truncated ---")
            break
    if not texts:
        parts.append("(no source text available)")
    return "\n".join(parts)


# ---------- Generation ----------

def generate(key: str, force: bool = False) -> dict:
    """Return the cached brief, or generate, cache and return a new one. Raises KeyError for unknown key."""
    if not force:
        cached = get_cached(key)
        if cached:
            return cached

    launch = db.get_launch(key)
    if launch is None:
        raise KeyError(key)

    api_key = os.environ.get("FORTYTWO_API_KEY")
    if not api_key:
        raise RuntimeError("FORTYTWO_API_KEY не задан")

    from openai import OpenAI  # lazy: the dashboard must run without the package or the key

    # max_retries: the SDK retries 429/5xx itself and honours Retry-After, so a backfill loop can stay dumb
    client = OpenAI(base_url=BASE_URL, api_key=api_key, max_retries=6, timeout=3600)
    lang = os.environ.get("SUMMARY_LANG", "ru")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},   # stable prefix -> prompt cache
            {"role": "user", "content": build_user_message(launch, _source_texts(launch), lang)},
        ],
        response_format=RESPONSE_FORMAT,
        extra_body={"reasoning_effort": REASONING_EFFORT},
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    content = resp.choices[0].message.content or ""
    brief = LaunchBrief.model_validate_json(content)
    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    created_at = datetime.now(timezone.utc).isoformat()
    _store(key, brief, prompt_tokens, completion_tokens, created_at)
    return _with_meta(brief, MODEL, REASONING_EFFORT, prompt_tokens, completion_tokens, created_at)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.summarize <launch key>")
    result = generate(sys.argv[1], force=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
