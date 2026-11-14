"""Run the golden eval set through the real agent (same code path as the UI) and grade it.

  uv run python evals/run_evals.py                       # all items, current default model
  uv run python evals/run_evals.py --only demo --repeat 5
  uv run python evals/run_evals.py --model claude-opus-5-5 --concurrency 4

--only matches item ids or tags. Results go to evals/results/<timestamp>-<model>.jsonl, with a summary table on
stdout. Each item runs in a fresh session; multi-turn items reuse one session across their turns.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from evals.grading import grade  # noqa: E402


async def run_item(item: dict, sem: asyncio.Semaphore) -> dict:
    from ahdc_agent.agent import AgentSession  # imported after env overrides are set

    async with sem:
        t0 = time.monotonic()
        answer, stats, error, first_answer = None, [], None, None
        try:
            async with AgentSession() as session:
                for q in item["turns"]:
                    answer = None
                    tq = time.monotonic()
                    async for ev in session.ask(q):
                        if ev["type"] == "answer":
                            if answer is None:
                                first_answer = round(time.monotonic() - tq, 1)
                            answer = ev
                        elif ev["type"] == "error":
                            error = ev["message"]
                        elif ev["type"] == "done":
                            stats.append(ev["stats"])
        except Exception as e:  # keep the run going
            error = f"{type(e).__name__}: {e}"
        results = grade(answer, item["checks"])
        last = stats[-1] if stats else {}
        return {
            "id": item["id"], "tags": item.get("tags", []), "passed": all(r["ok"] for r in results),
            "checks": results, "headline": answer["headline"] if answer else None,
            "confidence": f"{answer['confidence']['level']} {answer['confidence']['score']}/5" if answer else None,
            "error": error, "seconds": last.get("seconds"), "first_answer_s": first_answer,
            "review": answer.get("reviewed") if answer else None,
            "review_report": answer.get("review_report") if answer else None, "tool_calls": last.get("tool_calls"),
            "cost_usd": round(sum((s.get("cost_usd") or 0) for s in stats), 4),
            "wall_seconds": round(time.monotonic() - t0, 1),
        }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="item ids or tags")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--model")
    ap.add_argument("--effort")
    args = ap.parse_args()
    if args.model:
        os.environ["AHDC_MODEL"] = args.model
    if args.effort:
        os.environ["AHDC_EFFORT"] = args.effort
    from ahdc_agent.agent import EFFORT, MODEL

    items = yaml.safe_load((ROOT / "evals" / "golden.yaml").read_text())["items"]
    if args.only:
        items = [i for i in items if i["id"] in args.only or set(i.get("tags", [])) & set(args.only)]
    jobs = [i for i in items for _ in range(args.repeat)]
    print(f"Running {len(jobs)} item-runs ({len(items)} items × {args.repeat}) on {MODEL} / {EFFORT}, "
          f"concurrency {args.concurrency}\n", flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()
    results = []
    for coro in asyncio.as_completed([run_item(i, sem) for i in jobs]):
        r = await coro
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  {mark}  {r['id']:<26} {r['seconds'] or 0:>5}s  ${r['cost_usd']:.3f}  {r['confidence'] or '':<10} "
              f"{(r['headline'] or r['error'] or '')[:80]}", flush=True)
        for c in r["checks"]:
            if not c["ok"]:
                print(f"          ✗ {c['check']}: {c['detail'][:150]}")

    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{MODEL}-{EFFORT}.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n")

    secs = [r["seconds"] for r in results if r["seconds"]]
    passed = sum(r["passed"] for r in results)
    by_item: dict[str, list[bool]] = {}
    for r in results:
        by_item.setdefault(r["id"], []).append(r["passed"])
    print(f"\n{MODEL} / {EFFORT}: {passed}/{len(results)} passed ({100 * passed / len(results):.0f}%)")
    if args.repeat > 1:
        for k, v in by_item.items():
            print(f"  {k:<26} {sum(v)}/{len(v)}")
    if secs:
        print(f"seconds per item: median {statistics.median(secs):.1f}, max {max(secs):.1f}")
    fa = [r["first_answer_s"] for r in results if r.get("first_answer_s")]
    if fa:
        print(f"seconds to first answer shown: median {statistics.median(fa):.1f}, max {max(fa):.1f}")
    reviews = [r["review"] for r in results if r.get("review")]
    if reviews:
        print(f"methods review: {sum(v.startswith('PASS') for v in reviews)}/{len(reviews)} passed first time")
    print(f"cost: total ${sum(r['cost_usd'] for r in results):.2f}, "
          f"mean ${statistics.mean(r['cost_usd'] for r in results):.3f} per item")
    print(f"wall clock {time.monotonic() - t0:.0f}s · results: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
