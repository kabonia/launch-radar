"""Generate an AI brief for every launch in launches.db, in parallel, until done.

  .venv/bin/python scripts/backfill_summaries.py            # only launches without a brief
  .venv/bin/python scripts/backfill_summaries.py --force    # regenerate everything
  .venv/bin/python scripts/backfill_summaries.py --workers 8 --loop 600
      --loop N: when finished, sleep N seconds and start over (picks up new launches; with
                --force it keeps regenerating forever - the "burn credits" mode)

Rate limits: the SDK retries 429 and honours Retry-After, so this loop just keeps going.
Core tier is 20 requests/min and 500/hour per model, so throughput is bounded by the tier,
not by this script; bigger requests (max reasoning, long sources) spend more per call.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, summarize  # noqa: E402


def keys_to_do(force: bool) -> list[str]:
    all_keys = [row["key"] for row in db.get_launches()]
    if force:
        return all_keys
    return [k for k in all_keys if summarize.get_cached(k) is None]


def one(key: str, force: bool) -> tuple[str, str]:
    t0 = time.time()
    try:
        data = summarize.generate(key, force=force)
        m = data["meta"]
        return key, f"ok  {time.time() - t0:5.1f}s  in={m['prompt_tokens']} out={m['completion_tokens']}"
    except Exception as e:  # keep the batch alive; the key stays uncached and is retried next pass
        return key, f"ERR {type(e).__name__}: {str(e)[:120]}"


def run_pass(force: bool, workers: int) -> int:
    todo = keys_to_do(force)
    print(f"[pass] {len(todo)} launches to process, reasoning={summarize.REASONING_EFFORT}, workers={workers}")
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, k, force): k for k in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            key, status = fut.result()
            print(f"[{i}/{len(todo)}] {key[:40]:40} {status}", flush=True)
    s = summarize.cache_stats()
    print(f"[totals] briefs={s['briefs']} in={s['prompt_tokens']} out={s['completion_tokens']} "
          f"~${s['est_usd']}", flush=True)
    return len(todo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="regenerate briefs that already exist")
    ap.add_argument("--workers", type=int, default=4, help="parallel requests (429 concurrency errors -> lower it)")
    ap.add_argument("--loop", type=int, default=0, help="seconds to sleep between passes; 0 = single pass")
    args = ap.parse_args()

    while True:
        run_pass(args.force, args.workers)
        if not args.loop:
            break
        print(f"[sleep] {args.loop}s", flush=True)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
